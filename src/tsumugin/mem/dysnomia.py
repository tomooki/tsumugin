"""Dysnomia 外部バイナリの MEMBackend ラッパ (M5 / REQ-019/020/406 / EDGE-006 / NFR-106)。

``DysnomiaBackend`` は MEM 入力 (``MEMInput``) を一時領域へ**決定論的に生成**し、Dysnomia
バイナリを**遅延起動** (``shutil.which`` or ``binary_path``) して密度マップ (.grd) 等を回収し
``MEMResult`` を構成する。``GSASIIBackend`` の遅延 import + available パターンと同型で、
外部バイナリ未検出時は ``MEMUnavailableError`` へ縮退する (REQ-020/EDGE-006)。

【入出力ファイル契約固定 (REQ-406/NFR-106)】: 入力ファイル (.mem) は structure_factors の
  (h,k,l) 昇順をそのまま反映した固定フォーマットで生成する (乱数不使用・同一入力でビット同一)。
【非破壊 (P2)】: 生の ``MEMInput`` は改変しない。回収した密度はファイル (path) 参照で保持し、
  メモリには要約統計 (min/max) のみ持つ (``MEMResult`` の契約)。
【core-only import (REQ-403)】: ``import tsumugin.mem.dysnomia`` は numpy のみで成功する。
  subprocess/shutil は stdlib。Dysnomia python パッケージがあれば使うが、無くても import 成功
  (遅延 import)。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import MEMUnavailableError
from .base import MEMDensityMap, MEMResult
from .inputgen import MEMInput

# 【入力ファイル契約バージョン (REQ-406/NFR-106)】: フォーマットを凍結する識別子。
#   実バイナリ導入時に入出力契約をこのバージョンで固定する。
_INPUT_FORMAT_VERSION = 1

# 【入力/出力ファイル名 (契約固定)】: 一時領域内の決定論的ファイル名。
_INPUT_FILENAME = "tsumugin_mem.mem"
_DENSITY_FILENAME = "tsumugin_mem.grd"


@dataclass(frozen=True)
class DysnomiaBackend:
    """Dysnomia 外部バイナリの MEMBackend ラッパ (遅延起動)。🔵 REQ-019/020/406/FR-602

    【入出力ファイル契約固定 (REQ-406/NFR-106)】: 一時領域に MEM 入力ファイルを決定論的に生成し、
      Dysnomia バイナリを実行し、密度マップ (.grd) 等を回収する。生データ改変はしない (P2)。
    【未導入 (REQ-020/EDGE-006)】: バイナリ未検出時は run() が ``MEMUnavailableError`` へ縮退する
      (M4 で errors.py 定義済)。``import tsumugin.mem.dysnomia`` はコア (numpy) のみで成功する。
    """

    binary_path: str | None = None  # 【Dysnomia 実行ファイルパス (None は PATH 探索)】 🔵
    work_dir: str | None = None  # 【入出力一時領域 (None は tempdir)】 🔵
    name: str = "dysnomia"

    # ---- バイナリ解決 (テストで差し替え可能) --------------------------------

    def _resolve_binary(self) -> str | None:
        """Dysnomia 実行ファイルを解決する。未検出なら None を返す。🔵 REQ-020/EDGE-006

        ``binary_path`` 指定時はそれを (実在すれば) 用い、未指定なら ``shutil.which("dysnomia")``
        で PATH 探索する。テストは本メソッドを差し替えて未検出/検出を模せる (副作用なし)。
        """
        if self.binary_path is not None:
            return self.binary_path if Path(self.binary_path).exists() else None
        return shutil.which("dysnomia")

    # ---- 入力生成 (決定論・契約固定) ----------------------------------------

    def _render_input(self, mem_input: MEMInput) -> str:
        """MEMInput を Dysnomia 入力フォーマットへ決定論的に整形する。🔵 REQ-406/NFR-106

        structure_factors の (h,k,l) 昇順 (inputgen が保証) をそのまま行順に反映した固定
        フォーマットで文字列を組む (乱数不使用・同一入力でビット同一)。``mem_input`` は改変しない
        (P2)。実データ (格子/密度種別/反射) のみを書き出し、生成側でソート等の並べ替えはしない。
        """
        a, b, c, al, be, ga = mem_input.lattice
        lines = [
            f"# tsumugin MEM input (format v{_INPUT_FORMAT_VERSION})",
            f"DENSITY {mem_input.density_kind}",
            f"SPACEGROUP {mem_input.space_group}",
            f"CELL {a:.8f} {b:.8f} {c:.8f} {al:.8f} {be:.8f} {ga:.8f}",
            "GRID {0} {1} {2}".format(*mem_input.grid_shape),
            f"LAMBDA {mem_input.lambda_start:.8f}",
            f"NREFL {len(mem_input.structure_factors)}",
            "# h k l |F_obs| phase d_spacing",
        ]
        # structure_factors は inputgen が (h,k,l) 昇順で構成する契約。並べ替えず順序を保つ。
        for sf in mem_input.structure_factors:
            h, k, l = sf.hkl  # noqa: E741 - 結晶学慣習の l を許容
            lines.append(
                f"{h} {k} {l} {sf.f_obs:.8f} {sf.phase:.8f} {sf.d_spacing:.8f}"
            )
        return "\n".join(lines) + "\n"

    # ---- 実行 --------------------------------------------------------------

    def run(self, mem_input: MEMInput) -> MEMResult:
        """入力ファイル生成 → バイナリ実行 → 密度回収。未導入は MEMUnavailableError。🔵 REQ-019/020/EDGE-006

        【未導入縮退 (REQ-020/EDGE-006)】: ``_resolve_binary`` が None (PATH/binary_path 未解決)
          なら ``MEMUnavailableError`` を送出し、extra/バイナリ導入手順を案内する (破壊はしない)。
        【入出力契約 (REQ-406/NFR-106)】: 一時領域に決定論的入力ファイルを書き出し (契約固定)、
          Dysnomia バイナリを遅延起動して密度マップ (.grd) を回収する。
        【非破壊 (P2)】: ``mem_input`` は改変しない。密度は path 参照で ``MEMResult`` に保持する。
        """
        binary = self._resolve_binary()
        if binary is None:
            raise MEMUnavailableError(
                "Dysnomia バイナリが見つかりません (PATH/binary_path で未解決)。"
                "Dysnomia を導入して PATH に通すか DysnomiaBackend(binary_path=...) を "
                "指定してください (optional extra は 0058 で列挙予定)。"
            )

        # 【一時領域】: work_dir 指定時はそこへ、未指定なら tempdir を用いる (契約固定ファイル名)。
        if self.work_dir is not None:
            work = Path(self.work_dir)
            work.mkdir(parents=True, exist_ok=True)
            return self._run_in(work, binary, mem_input)
        with tempfile.TemporaryDirectory(prefix="tsumugin-mem-") as tmp:
            return self._run_in(Path(tmp), binary, mem_input)

    def _run_in(self, work: Path, binary: str, mem_input: MEMInput) -> MEMResult:
        """作業ディレクトリ ``work`` で入力生成 → バイナリ実行 → 密度回収を行う。🔵 REQ-406/EDGE-006

        入力ファイルは契約固定名 (``_INPUT_FILENAME``) で決定論的に書き出す (P2: 入力不改変)。
        Dysnomia を遅延起動し、密度マップ (.grd) を回収して ``MEMResult`` を構成する。

        【実行失敗 / 出力欠落の縮退 (LOW-8/EDGE-006)】: バイナリ解決成功後の実行失敗
          (``CalledProcessError``) や .grd 未生成 (``FileNotFoundError`` / ``OSError`` /
          ``ValueError``) は素の例外で漏らさず ``MEMUnavailableError`` へ変換する (未検出縮退と対称)。
          ``subprocess.run`` は shell=False のリスト形式を維持する (インジェクション回避)。
        """
        input_path = work / _INPUT_FILENAME
        input_path.write_text(self._render_input(mem_input), encoding="utf-8")

        # 【遅延起動】: Dysnomia を subprocess で実行する (入力ファイルを引数に取る契約固定)。
        try:
            subprocess.run(
                [binary, str(input_path)],
                cwd=str(work),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise MEMUnavailableError(
                f"Dysnomia の実行に失敗しました (returncode={exc.returncode})。"
                "入力ファイル契約・バイナリ導入状態を確認してください。"
            ) from exc

        density_path = work / _DENSITY_FILENAME
        try:
            density_map = self._collect_density(density_path, mem_input)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise MEMUnavailableError(
                f"Dysnomia が密度マップ (.grd) を生成しませんでした ({density_path.name} 欠落/不正)。"
                "バイナリ導入状態・入出力契約を確認してください。"
            ) from exc
        return MEMResult(density_map=density_map)

    def _collect_density(self, density_path: Path, mem_input: MEMInput) -> MEMDensityMap:
        """回収した密度マップ (.grd) から要約統計 (min/max) を組む。🔵 REQ-027

        重い密度グリッドはメモリに引き回さず path 参照で保持し、統計のみ抽出する (非破壊/軽量)。
        本ヘルパは実バイナリ smoke (@mem) 経路で用いる。
        """
        values = np.loadtxt(density_path)
        return MEMDensityMap(
            path=str(density_path),
            density_kind=mem_input.density_kind,
            grid_shape=mem_input.grid_shape,
            min_density=float(np.min(values)),
            max_density=float(np.max(values)),
        )

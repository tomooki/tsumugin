# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec (one-dir) — Tsumugin Workbench desktop sidecar (V2c C1, ADR-0001).

Tier1 = コア + web extra のみ同梱。GSAS-II / pymatgen / dynesty / MCP SDK 等の重量物・任意 extra
依存は明示的に ``excludes`` する — これらは ``tsumugin`` 内で遅延 import + フォールバック
(``GSASUnavailableError``/``MPUnavailableError`` 等) されている契約 (CLAUDE.md「実装上の不変条件」)
なので、未同梱でも import 時に静かに機能を諦めるだけで起動自体は壊れない。GSAS-II はローカル
導入前提 (desktop/README.md) — sidecar は起動時に import 可否を判定し GET /api/state の
``status.gsas_available`` で表明する (``tsumugin.backends.gsasii.gsasii_available``)。

ビルド:
    uv run pyinstaller desktop/sidecar/sidecar.spec --noconfirm
    (通常は desktop/sidecar/build_sidecar.ps1 経由で呼ぶ — 出力を
    desktop/src-tauri/binaries/ へ配置するところまで面倒を見る)

出力 (one-dir): desktop/sidecar/dist/tsumugin-workbench-sidecar/
    tsumugin-workbench-sidecar.exe  … 起動 exe (Tauri へは build_sidecar.ps1 が target-triple
                                        付きでリネームコピーする)
    _internal/                       … 依存一式 (exe と同じディレクトリに必須, PyInstaller onedir
                                        規約)
    frontend_dist/                   … 同梱 UI (frontend/dist の datas コピー)
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# 【SPECPATH】: PyInstaller が spec ファイルを ``exec()`` するため ``__file__`` は未定義
#   (NameError)。代わりに PyInstaller が spec 実行時の名前空間へ注入する組み込み変数
#   ``SPECPATH`` (spec ファイルのディレクトリ, 常に絶対パス) を使う。
_SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 — PyInstaller が exec 時に注入
_REPO_ROOT = _SPEC_DIR.parents[1]
_SRC_DIR = _REPO_ROOT / "src"
_FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"
_ENTRY = _SPEC_DIR / "tsumugin_workbench_sidecar.py"

if not _FRONTEND_DIST.is_dir():
    raise SystemExit(
        f"frontend/dist が見つかりません ({_FRONTEND_DIST}). "
        "先に `cd frontend && npm run build` を実行してください。"
    )

# 【Tier1 exclude リスト】: gsas/nested/mem/oed/mp/absorption/echem/mcp extra のランタイム依存
#   (CLAUDE.md 技術スタック表の optional-dependencies と対応)。すべて `tsumugin` 側で
#   遅延 import + Unavailable 系エラーへのフォールバックが実装済みなので、未同梱でも
#   Tier1 の非対応機能 (refine/multistart/sequential/phaseid の一部) がエラーへ縮退するだけ。
_HEAVY_EXCLUDES = [
    "GSASII",
    "pymatgen",
    "mp_api",
    "dynesty",
    "galvani",
    "mcp",
    "periodictable",
    "pycifrw",
    "scipy",
    "pytest",
    # 【V2c レビュー指摘】: PIL/Pygments はどの tsumugin モジュールも直接 import しないが、
    #   matplotlib (pymatgen-core の非 extra 依存) 経由で PyInstaller の静的解析に引っかかり
    #   同梱されていた (~13MB, PIL のみ確認 — pymatgen 自体は除外済みなのに Pillow だけ残る)。
    #   matplotlib/pymatgen 系を実際に使う経路が sidecar には無いため、Tier1 exclude リストの
    #   趣旨 (遅延 import + Unavailable フォールバック済み機能のみ非同梱) に合わせて追加する。
    "PIL",
    "pygments",
]

hiddenimports = list(
    dict.fromkeys(
        [
            *collect_submodules("uvicorn"),
            *collect_submodules("fastapi"),
            *collect_submodules("starlette"),
            *collect_submodules("multipart"),
            *collect_submodules("anyio"),
            *collect_submodules(
                "tsumugin",
                filter=lambda name: not any(bad in name for bad in _HEAVY_EXCLUDES),
            ),
            "h11",
            "click",
            "numpy",
        ]
    )
)

a = Analysis(
    [str(_ENTRY)],
    pathex=[str(_SRC_DIR)],
    binaries=[],
    datas=[(str(_FRONTEND_DIST), "frontend_dist")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_HEAVY_EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tsumugin-workbench-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="tsumugin-workbench-sidecar",
)

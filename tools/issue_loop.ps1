<#
.SYNOPSIS
    Issue 自動処理ループの周回ドライバ (段 0: dry-run 既定)。

.DESCRIPTION
    `loop:queued` かつ指定ゲートの Issue を拾い、1 件ずつ `/issue-work` を回す。
    設計: docs/design/issue-auto-loop/architecture.md
    周回の中身: .claude/skills/issue-work/SKILL.md

    既定は **dry-run** — S1 (実地確認) までで止まり、計画レポートを
    scratchpad/issue-loop/ に書くだけで GitHub へは 1 バイトも書かない。
    実際に着手させるには -Apply を明示する。

.PARAMETER Gate
    対象ゲート級。fast / gsas / bench / human。
    ⚠ gsas / bench は **このローカル機でしか受け入れ判定ができない** (GSAS-II / TOPAS / 実データ)。
    human は着手対象ではないので、指定しても 0 件で返る。

.PARAMETER Max
    1 周で拾う件数。既定 1。gsas は実精密化で CPU を掴むので 2 を超えないこと。

.PARAMETER Apply
    dry-run を解除し、worktree を切って実際に着手させる。

.EXAMPLE
    .\tools\issue_loop.ps1 -Gate fast
    # dry-run。計画レポートだけを書く。

.EXAMPLE
    .\tools\issue_loop.ps1 -Gate gsas -Max 2 -Apply
    # ローカルワーカーを 2 本、worktree 隔離で起動する。
#>
[CmdletBinding()]
param(
    [ValidateSet('fast', 'gsas', 'bench', 'human')]
    [string]$Gate = 'fast',

    [ValidateRange(1, 4)]
    [int]$Max = 1,

    [switch]$Apply,

    # 何が拾われるかだけを表示して終わる (ワーカーを起動しない)。
    [switch]$ListOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$reportDir = Join-Path $repoRoot 'scratchpad\issue-loop'

if (-not (Test-Path $reportDir)) {
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}

# --- gate:human は設計上の着手対象外 (§6 ハード境界) ---------------------------
if ($Gate -eq 'human') {
    Write-Host "gate:human は人間の判断・外部への働きかけが本体であり、ループの着手対象ではない。" -ForegroundColor Yellow
    Write-Host "調査だけさせたい場合は Issue に @claude で個別に頼むこと。"
    return
}

# --- キュー取得 ----------------------------------------------------------------
$ghArgs = @('issue', 'list', '--state', 'open', '--label', 'loop:queued',
    '--label', "gate:$Gate", '--json', 'number,title,labels', '--limit', '100')
$raw = & gh @ghArgs
if ($LASTEXITCODE -ne 0) { throw "gh issue list が失敗した (exit $LASTEXITCODE)" }

# WARN 空キューを「1 件」と読まないこと (実測で番号なしの要素でワーカーを起動しかけた)。
#      ConvertFrom-Json は "[]" を **空配列 1 個のオブジェクト**としてパイプへ流すため、
#      `$raw | ConvertFrom-Json | ...` と直接繋ぐと空が 1 件に化ける。
#      いったん変数へ代入すると展開されて 0 件になる。加えて number を持つ要素だけ数え、
#      「空を正常と答える」経路を構造的に塞ぐ。
$parsed = $raw | ConvertFrom-Json
$queued = @($parsed | Where-Object { $null -ne $_ -and $null -ne $_.number })
if ($queued.Count -eq 0) {
    Write-Host "loop:queued かつ gate:$Gate の Issue は無い。"
    return
}

Write-Host "gate:$Gate のキュー: $($queued.Count) 件 (拾うのは最大 $Max 件)"

$picked = @($queued | Select-Object -First $Max)

if ($ListOnly) {
    foreach ($issue in $picked) {
        Write-Host ("  #{0}  {1}" -f $issue.number, $issue.title)
    }
    Write-Host "(-ListOnly のため着手しない)"
    return
}

foreach ($issue in $picked) {
    $n = $issue.number

    # --- 防御: 番号の無い要素で仕事を始めない (空入力を「正常」と答えない) ---------
    if (-not $n) {
        Write-Host "  WARN 番号を持たない要素がキューに混じった。着手せず飛ばす。" -ForegroundColor Yellow
        continue
    }

    $branch = "auto/issue-$n"

    # --- 冪等: 既にブランチがあるなら着手済とみなして飛ばす ---------------------
    & git -C $repoRoot show-ref --verify --quiet "refs/heads/$branch"
    $branchExists = ($LASTEXITCODE -eq 0)
    if ($branchExists) {
        Write-Host "  #$n : ブランチ $branch が既にある → 着手済とみなして飛ばす" -ForegroundColor DarkGray
        continue
    }

    Write-Host ""
    Write-Host "=== #$n $($issue.title)" -ForegroundColor Cyan

    if (-not $Apply) {
        # --- dry-run: S1 まで。GitHub へは書かない -----------------------------
        $report = Join-Path $reportDir "$n-plan.md"
        Write-Host "  dry-run → $report"

        # ⚠ パイプで受けないこと (PS/bash 双方で終了コードが潰れる実測あり)。
        #    出力は変数に受け、$LASTEXITCODE を別途読む。
        $workerArgs = @('-p', "/issue-work $n --dry-run",
            '--permission-mode', 'acceptEdits',
            '--max-turns', '30',
            '--add-dir', $repoRoot)
        $out = & claude @workerArgs
        $code = $LASTEXITCODE

        Set-Content -Path $report -Value $out -Encoding utf8
        if ($code -ne 0) {
            Write-Host "  ⚠ claude が exit $code で終了した。レポートは途中までの可能性がある。" -ForegroundColor Yellow
        }
        else {
            Write-Host "  完了 (GitHub への書き込みなし)"
        }
        continue
    }

    # --- 本番: worktree を切ってバックグラウンドワーカーへ ----------------------
    # ⚠ worktree では editable install が main の src を指すため、ワーカー側で
    #    $env:PYTHONPATH="<worktree>\src" を必ず設定させる (SKILL.md §6)。
    #    これを忘れると全周回が静かに別ソースを検証する。
    & gh issue edit $n --add-label "loop:in-progress" --remove-label "loop:queued"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠ ラベル遷移に失敗した。着手しない。" -ForegroundColor Yellow
        continue
    }

    $workerArgs = @('--bg', '--worktree', $branch,
        '--permission-mode', 'acceptEdits',
        '--max-turns', '60',
        '-p', "/issue-work $n")
    & claude @workerArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠ ワーカー起動に失敗した (exit $LASTEXITCODE)。ラベルを戻すこと。" -ForegroundColor Yellow
    }
    else {
        Write-Host "  ワーカーを起動した (claude agents で状況を見る)"
    }
}

Write-Host ""
Write-Host "周回終了。"
if (-not $Apply) {
    Write-Host "レポート: $reportDir"
    Write-Host "実着手させるには -Apply を付ける。"
}

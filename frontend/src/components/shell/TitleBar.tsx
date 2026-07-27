import { useState } from "react";
import type { GuiMode } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { SettingsModal } from "../settings/SettingsModal";
import { sm } from "../settings/SettingsModal.strings";
import { Chip } from "../common";
import "./shell.css";

interface TitleBarProps {
  onModeChange: (mode: GuiMode) => void;
  /** True while state.shell.source === "none" (Welcome screen, REQ-GUI-017)
   * — there is no project session to attach a final_selection_mode switch
   * to, so MANUAL/AUTO is disabled rather than silently no-op-ing. */
  disabled?: boolean;
}

/** 56px title bar: TSUMUGIN logo + version/GSAS-II chips, centred mode
 * toggle, EN/日本語 segment + status chips. Handoff README §1. */
export function TitleBar({ onModeChange, disabled = false }: TitleBarProps) {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const idle = state.shell?.agent.idle ?? state.mode === "manual";
  // Gear → SETTINGS modal (api-contract.md §アプリ設定): local UI state, not
  // global store — nothing outside this button cares whether the modal is
  // open. Shown on both the Welcome screen and the workbench (TitleBar
  // renders unconditionally in App.tsx before the isWelcome branch), per the
  // contract's "Welcome 画面からも開ける".
  const [settingsOpen, setSettingsOpen] = useState(false);

  // null = /api/state 未取得 ("…" 表示)。false は反転チップで目立たせる。
  const chainVerified = state.shell?.ledger?.verified ?? null;
  // FR-404: 実測のトークンと経過時間のみ (金額は出さない)。
  const cost = {
    tokens: (state.shell?.agent?.tokens ?? 0).toLocaleString("en-US"),
    minutes: Math.round((state.shell?.agent?.wall_time_s ?? 0) / 60),
  };

  const modes: { key: GuiMode; labelKey: "mode.manual.label" | "mode.auto.label"; subKey: "mode.manual.sub" | "mode.auto.sub" }[] = [
    { key: "manual", labelKey: "mode.manual.label", subKey: "mode.manual.sub" },
    { key: "auto", labelKey: "mode.auto.label", subKey: "mode.auto.sub" },
  ];

  return (
    <div className="title-bar">
      <div className="title-bar__brand">
        <span className="title-bar__logo">TSUMUGIN</span>
        <span className="title-bar__version">v0.3 · M0–M11</span>
        <Chip variant="accent">{t("shell.gsasChip")}</Chip>
      </div>

      <div className="title-bar__mode-wrap">
        <div className="mode-toggle blueprint">
          {modes.map((m) => {
            const active = state.mode === m.key;
            return (
              <button
                key={m.key}
                type="button"
                className={`mode-toggle__btn${active ? " mode-toggle__btn--active" : ""}`}
                disabled={disabled}
                onClick={() => onModeChange(m.key)}
              >
                <span className="mode-toggle__dot" />
                <span>
                  <span className="mode-toggle__label">{t(m.labelKey)}</span>
                  <span className="mode-toggle__sub">{t(m.subKey)}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="title-bar__right">
        <button
          type="button"
          className="title-bar__settings-btn"
          aria-label={sm(lang, "settings.gear.label")}
          title={sm(lang, "settings.gear.label")}
          onClick={() => setSettingsOpen(true)}
        >
          ⚙
        </button>
        <div className="lang-seg">
          <button
            type="button"
            className={`lang-seg__btn${state.lang === "en" ? " lang-seg__btn--active" : ""}`}
            onClick={() => dispatch({ type: "SET_LANG", lang: "en" })}
          >
            EN
          </button>
          <button
            type="button"
            className={`lang-seg__btn${state.lang === "ja" ? " lang-seg__btn--active" : ""}`}
            onClick={() => dispatch({ type: "SET_LANG", lang: "ja" })}
          >
            日本語
          </button>
        </div>
        {/* 【可変幅】: 状態チップ群は狭いウィンドウで畳む (歯車と言語切替を優先。
           同じ情報はステータスバーにも出る)。 */}
        <div className="title-bar__chips">
        <Chip>
          <span className="title-bar__dot" />
          {t("shell.nonDestructive")}
        </Chip>
        {/* 実状態を出す。プロトタイプはどちらも固定文字列だった — 追記専用台帳の
            verify() を常に TRUE と表示するのは、改竄検知そのものを無効にする嘘。 */}
        <Chip variant={chainVerified === false ? "inverted" : undefined}>
          {`ledger.verify() = ${chainVerified === null ? "…" : chainVerified ? "TRUE" : "FALSE"}`}
        </Chip>
        <Chip>{idle ? t("status.cost.idle") : t("status.cost.active", cost)}</Chip>
        </div>
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

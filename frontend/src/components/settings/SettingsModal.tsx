import { useEffect, useState } from "react";
import { ApiError, getSettings, getState, postSettings, postSettingsClear } from "../../api/client";
import type { SettingsState } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Btn } from "../common";
import "./SettingsModal.css";
import { sm } from "./SettingsModal.strings";

interface SettingsModalProps {
  onClose: () => void;
}

type Busy = "save" | "clear" | null;

/** api-contract.md §アプリ設定 (資格情報) — Materials Project トークン. The
 * gear button that opens this modal lives in TitleBar (visible on both the
 * Welcome screen and the workbench, per the contract's "Welcome 画面からも
 * 開ける") — this component is only the modal body, mounted conditionally by
 * the parent's local open state.
 *
 * The 絶対規則 (api-contract.md) this component must honour: the key itself
 * is NEVER returned by the API (GET /api/settings only ever sends back
 * mp_api_key_set/hint/source) and must never linger in this component's own
 * state either once it has been sent — the input is cleared immediately
 * after a successful SAVE (and on CLEAR), and error messages never echo the
 * typed value back (ApiError.message is server text, not the input state). */
export function SettingsModal({ onClose }: SettingsModalProps) {
  const { lang } = useI18n();
  const { dispatch } = useStore();
  const t = (key: Parameters<typeof sm>[1], vars?: Record<string, string | number>) => sm(lang, key, vars);

  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<Busy>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((s) => {
        if (!cancelled) setSettings(s);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            t("settings.loadError", { message: err instanceof ApiError ? err.message : String(err) }),
          );
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Re-syncs BOTH this modal's own masked state AND the shared shell state
  // (state.shell.status.mp_available) — the latter is what StatusBar's chip
  // and PhaseIdTab's disabled-controls read (api-contract.md "GET /api/state
  // の status.mp_available (相同定ボタンの事前 disabled に使う)"), so a
  // SAVE/CLEAR here must be visible there without a page reload.
  async function refetch() {
    const [s, shell] = await Promise.all([getSettings(), getState()]);
    setSettings(s);
    dispatch({ type: "SET_SHELL", shell });
  }

  async function handleSave() {
    const value = key.trim();
    if (!value || busy) return;
    setError(null);
    setMessage(null);
    setBusy("save");
    try {
      await postSettings(value);
      // Cleared on success regardless of what refetch() below does — the
      // token must not linger in this component's state once the backend
      // has it.
      setKey("");
      await refetch();
      setMessage(t("settings.saveSuccess"));
    } catch (err) {
      setError(
        t("settings.saveError", { message: err instanceof ApiError ? err.message : String(err) }),
      );
    } finally {
      setBusy(null);
    }
  }

  async function handleClear() {
    if (busy) return;
    setError(null);
    setMessage(null);
    setBusy("clear");
    try {
      await postSettingsClear();
      setKey("");
      await refetch();
      setMessage(t("settings.clearSuccess"));
    } catch (err) {
      setError(
        t("settings.clearError", { message: err instanceof ApiError ? err.message : String(err) }),
      );
    } finally {
      setBusy(null);
    }
  }

  const statusLabel = (() => {
    if (!settings) return t("settings.status.loading");
    if (settings.mp_api_key_set && settings.mp_api_key_source === "env") {
      return t("settings.status.setEnv");
    }
    if (settings.mp_api_key_set) {
      return t("settings.status.setSettings", { hint: settings.mp_api_key_hint ?? "" });
    }
    return t("settings.status.unset");
  })();

  return (
    // Backdrop click closes (the dialog itself stops propagation below) —
    // role="presentation" since this div is a click target, not semantic
    // content (the actual dialog semantics live on .settings-modal__dialog).
    <div className="settings-modal__backdrop" onClick={onClose} role="presentation">
      <div
        className="settings-modal__dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("settings.title")}
      >
        <BlueprintCard heading={t("settings.title")} className="settings-modal__card">
          <div className="settings-modal__body">
            <div className="settings-modal__section-heading">{t("settings.mp.heading")}</div>
            <div className="settings-modal__status">{statusLabel}</div>
            {settings?.mp_api_key_source === "env" && (
              <div className="settings-modal__note">{t("settings.envNote")}</div>
            )}
            <label className="settings-modal__field">
              <span>{t("settings.mp.inputLabel")}</span>
              <input
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={t("settings.mp.placeholder")}
                aria-label={t("settings.mp.inputLabel")}
                autoComplete="off"
              />
            </label>
            <div className="settings-modal__actions">
              <Btn
                type="button"
                variant="accent"
                disabled={!key.trim() || busy !== null}
                onClick={handleSave}
              >
                {busy === "save" ? t("settings.mp.saving") : t("settings.mp.save")}
              </Btn>
              <Btn type="button" variant="outline" disabled={busy !== null} onClick={handleClear}>
                {busy === "clear" ? t("settings.mp.clearing") : t("settings.mp.clear")}
              </Btn>
              <Btn type="button" variant="outline" onClick={onClose}>
                {t("settings.mp.close")}
              </Btn>
            </div>
            {message && (
              <div className="settings-modal__message settings-modal__message--success">{message}</div>
            )}
            {error && (
              <div className="settings-modal__message settings-modal__message--error">{error}</div>
            )}
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}

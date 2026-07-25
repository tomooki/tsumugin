import { useState } from "react";
import { ApiError, postStructureApply } from "../../api/client";
import type { Site } from "../../api/types";
import { ELEMENTS, elementLabel } from "../../data/elements";
import { useI18n } from "../../i18n";
import { siteList } from "../../state/reducer";
import { useStore } from "../../state/store";
import { BlueprintCard, Btn, PlaceholderPlot } from "../common";
import "./StructureTab.css";
import { interpolateLocal, STRUCT_LOCAL_STRINGS, type StructLocalKey } from "./StructureTab.strings";

type NumField = "x" | "y" | "z" | "occ" | "uiso";

const NUM_FIELDS: { field: NumField; header: string; lockable: boolean }[] = [
  { field: "x", header: "x", lockable: true },
  { field: "y", header: "y", lockable: true },
  { field: "z", header: "z", lockable: true },
  { field: "occ", header: "occ", lockable: false },
  { field: "uiso", header: "Uiso", lockable: false },
];

/** Is `field` fixed by symmetry for this site? Only x/y/z can be — occ/uiso
 * have no `lock` slot in the API contract (see `SiteLock` in api/types.ts). */
function isLocked(site: Site, field: NumField): boolean {
  if (field !== "x" && field !== "y" && field !== "z") return false;
  return !!site.lock[field];
}

function isReleased(site: Site, field: NumField): boolean {
  return !!site.rel[field];
}

interface NumCellProps {
  site: Site;
  field: NumField;
  lockedTip: string;
  onEdit: (field: NumField, value: string) => void;
  onToggleRelease: (field: NumField) => void;
}

function NumCell({ site, field, lockedTip, onEdit, onToggleRelease }: NumCellProps) {
  const locked = isLocked(site, field);
  const released = isReleased(site, field);
  const cellClass = locked
    ? "struct-num-cell struct-num-cell--locked"
    : released
      ? "struct-num-cell struct-num-cell--released"
      : "struct-num-cell";
  const inputClass = locked ? "struct-num-input struct-num-input--locked" : "struct-num-input";
  return (
    <td className={cellClass}>
      <span className="struct-num-cell__inner">
        <input
          type="checkbox"
          className="struct-checkbox"
          checked={released}
          disabled={locked}
          onChange={() => onToggleRelease(field)}
          title={locked ? lockedTip : undefined}
          aria-label={`release ${site.label} ${field}`}
        />
        <input
          className={inputClass}
          value={site[field]}
          disabled={locked}
          onChange={(e) => onEdit(field, e.target.value)}
          title={locked ? lockedTip : undefined}
          aria-label={`${site.label} ${field}`}
        />
      </span>
    </td>
  );
}

interface SiteRowProps {
  site: Site;
  lockedTip: string;
  deleteTip: string;
  onEdit: (id: string, field: keyof Site, value: string) => void;
  onToggleRelease: (id: string, field: NumField) => void;
  onDelete: (id: string) => void;
}

function SiteRow({ site, lockedTip, deleteTip, onEdit, onToggleRelease, onDelete }: SiteRowProps) {
  return (
    <tr>
      <td className="struct-cell">
        <input
          className="struct-label-input"
          value={site.label}
          onChange={(e) => onEdit(site.id, "label", e.target.value)}
          aria-label={`${site.label} label`}
        />
      </td>
      <td className="struct-cell">
        <select
          className="struct-el-select"
          value={site.el}
          onChange={(e) => onEdit(site.id, "el", e.target.value)}
          aria-label={`${site.label} element`}
        >
          {ELEMENTS.map((el) => (
            <option key={`${el.z}-${el.symbol}`} value={el.symbol}>
              {elementLabel(el)}
            </option>
          ))}
        </select>
      </td>
      {NUM_FIELDS.map(({ field }) => (
        <NumCell
          key={field}
          site={site}
          field={field}
          lockedTip={lockedTip}
          onEdit={(f, v) => onEdit(site.id, f, v)}
          onToggleRelease={(f) => onToggleRelease(site.id, f)}
        />
      ))}
      <td className="struct-note-cell">{site.note}</td>
      <td className="struct-cell struct-cell--del">
        <button type="button" className="struct-del-btn" title={deleteTip} onClick={() => onDelete(site.id)}>
          ×
        </button>
      </td>
    </tr>
  );
}

/** STRUCTURE tab — editable model. See handoff README §Centre pane item 6
 * and the `Tsumugin Workbench.dc.html` STRUCTURE section for the reference
 * markup this ports (grid 1.35fr / 1fr, SITES / CONSTRAINTS / MEM DENSITY). */
export function StructureTab() {
  const { t, lang } = useI18n();
  const { state, dispatch } = useStore();
  const [isApplying, setIsApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  function tl(key: StructLocalKey, vars?: Record<string, string | number>): string {
    const pair = STRUCT_LOCAL_STRINGS[key];
    return interpolateLocal(lang === "ja" ? pair.ja : pair.en, vars);
  }

  const sites = siteList(state);
  const structure = state.viewModel?.structure;
  const constraints = structure?.constraints ?? [];
  const memPeaks = structure?.mem_peaks ?? [];

  const lockedTip = t("site.tip.lockedSymmetry");
  const deleteTip = t("struct.deleteAtom");

  const releasedCount = sites.reduce(
    (acc, s) => acc + NUM_FIELDS.filter(({ field }) => isReleased(s, field) && !isLocked(s, field)).length,
    0,
  );

  function handleEdit(id: string, field: keyof Site, value: string) {
    dispatch({ type: "EDIT_SITE", id, field, value });
  }

  function handleToggleRelease(id: string, field: NumField) {
    dispatch({ type: "TOGGLE_SITE_RELEASE", id, field });
  }

  function handleDelete(id: string) {
    dispatch({ type: "DELETE_SITE", id });
  }

  function handleAddAtom() {
    dispatch({ type: "ADD_ATOM" });
  }

  function handleDiscard() {
    if (state.edits === 0) return;
    dispatch({ type: "DISCARD_EDITS" });
  }

  async function handleApply() {
    setApplyError(null);
    setIsApplying(true);
    try {
      await postStructureApply({ sites, note: "STRUCTURE tab · ReviseStructure" });
      dispatch({ type: "APPLY_EDITS" });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setApplyError(tl("struct.local.applyError", { message }));
    } finally {
      setIsApplying(false);
    }
  }

  let editStateText: string;
  let editStateClass = "struct-edit-state";
  if (isApplying) {
    editStateText = tl("struct.local.applying");
  } else if (state.edits > 0) {
    editStateText = t("edit.pending", { n: state.edits });
    editStateClass += " struct-edit-state--pending";
  } else if (state.applied) {
    editStateText = t("edit.applied");
    editStateClass += " struct-edit-state--applied";
  } else {
    editStateText = t("edit.none");
  }

  return (
    <div className="struct-tab">
      <div className="struct-tab__head">
        <span className="struct-tab__title">{t("struct.title")}</span>
        <span className="struct-tab__note">{t("struct.note")}</span>
      </div>
      <div className="struct-tab__grid">
        <BlueprintCard
          heading={t("struct.sites")}
          note={t("struct.sitesHint")}
          style={{ display: "flex", flexDirection: "column", minHeight: 0 }}
          bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
        >
          <div className="struct-sites__scroll tg-scroll">
            <table className="struct-table">
              <thead>
                <tr>
                  <th className="ta-left">{t("col.label")}</th>
                  <th className="ta-left">{t("col.elementZ")}</th>
                  {NUM_FIELDS.map(({ field, header }) => (
                    <th key={field} className="ta-right">
                      {header}
                    </th>
                  ))}
                  <th className="ta-left">{t("col.note")}</th>
                  <th className="ta-right" />
                </tr>
              </thead>
              <tbody>
                {sites.map((site) => (
                  <SiteRow
                    key={site.id}
                    site={site}
                    lockedTip={lockedTip}
                    deleteTip={deleteTip}
                    onEdit={handleEdit}
                    onToggleRelease={handleToggleRelease}
                    onDelete={handleDelete}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="struct-legend">
            <span className="struct-legend__item">
              <input type="checkbox" className="struct-checkbox" checked readOnly disabled />
              {t("struct.relLegend")}
            </span>
            <span className="struct-legend__note">{t("struct.lockLegend")}</span>
            <span className="struct-legend__summary">{t("site.releasedSummary", { n: releasedCount })}</span>
          </div>
          <div className="struct-controls">
            <Btn type="button" variant="accent" onClick={handleAddAtom}>
              {"+ "}
              {t("struct.addAtom")}
            </Btn>
            <span className={editStateClass}>{editStateText}</span>
            <span className="struct-controls__actions">
              <Btn
                type="button"
                variant="accent"
                className="struct-apply-btn"
                onClick={handleApply}
                disabled={isApplying}
              >
                {t("struct.applyEdits")}
              </Btn>
              <Btn
                type="button"
                variant="outline"
                onClick={handleDiscard}
                disabled={state.edits === 0 || isApplying}
                title={t("struct.discardTip")}
              >
                {t("struct.discardEdits")}
              </Btn>
            </span>
          </div>
          {applyError && <div className="struct-apply-error">{applyError}</div>}
          <div className="struct-precedence">
            <span className="struct-precedence__bar" />
            <span className="struct-precedence__text">
              {t("struct.precedence")} {t("struct.editNote")}
            </span>
          </div>
        </BlueprintCard>
        <div className="struct-side">
          <BlueprintCard heading={t("struct.constraints")}>
            <div className="struct-constraints__list">
              {constraints.map((c, i) => (
                <div className="struct-constraints__row" key={`${c.kind}-${i}`}>
                  <span className="struct-constraints__expr">{c.text}</span>
                  <span className="struct-constraints__kind">
                    {c.ref ? `${c.kind} · ${c.ref}` : c.kind}
                  </span>
                </div>
              ))}
            </div>
          </BlueprintCard>
          <BlueprintCard
            heading={t("struct.memTitle")}
            style={{ display: "flex", flexDirection: "column", minHeight: 0 }}
            bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
          >
            <PlaceholderPlot label={t("struct.memPlaceholder")} />
            <div className="struct-mem__peaks">
              {memPeaks.map((p, i) => (
                <div key={i}>{`${p.position} · ${p.density} → ${p.assign}`}</div>
              ))}
            </div>
          </BlueprintCard>
        </div>
      </div>
    </div>
  );
}

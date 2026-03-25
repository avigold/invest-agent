import { useState } from "react";
import type { Rule } from "./FilterRule";

export interface SavedScreen {
  id: string;
  name: string;
  description?: string | null;
  is_template: boolean;
  filters: { rules: Rule[] };
  sort_by?: string | null;
  sort_desc?: boolean;
}

interface Props {
  screens: SavedScreen[];
  activeId: string | null;
  activeName: string | null;
  onLoad: (screen: SavedScreen) => void;
  onSave: (name: string) => void;
  onUpdate: () => void;
  onDelete: (id: string) => void;
  hasFilters: boolean;
  hasRows: boolean;
  onClear: () => void;
  onExport: () => void;
}

export default function SavedScreens({
  screens,
  activeId,
  activeName,
  onLoad,
  onSave,
  onUpdate,
  onDelete,
  hasFilters,
  hasRows,
  onClear,
  onExport,
}: Props) {
  const [showSave, setShowSave] = useState(false);
  const [saveName, setSaveName] = useState("");

  const templates = screens.filter((s) => s.is_template);
  const userScreens = screens.filter((s) => !s.is_template);
  const isUserScreen = activeId && !activeId.startsWith("tpl_");

  const handleSave = () => {
    if (saveName.trim()) {
      onSave(saveName.trim());
      setSaveName("");
      setShowSave(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Load selector */}
      <select
        value={activeId ?? ""}
        onChange={(e) => {
          const id = e.target.value;
          if (!id) return;
          const s = screens.find((s) => s.id === id);
          if (s) onLoad(s);
        }}
        className="rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none"
      >
        <option value="">
          {activeName ? activeName : "Load screen..."}
        </option>
        {templates.length > 0 && (
          <optgroup label="Templates">
            {templates.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </optgroup>
        )}
        {userScreens.length > 0 && (
          <optgroup label="Saved">
            {userScreens.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </optgroup>
        )}
      </select>

      {/* Save / Update */}
      {hasFilters && !showSave && (
        <>
          {isUserScreen ? (
            <button
              onClick={onUpdate}
              className="rounded border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors"
              title={`Update "${activeName}"`}
            >
              Update
            </button>
          ) : null}
          <button
            onClick={() => setShowSave(true)}
            className="rounded border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors"
          >
            Save As
          </button>
        </>
      )}

      {showSave && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") { setShowSave(false); setSaveName(""); }
            }}
            placeholder="Name..."
            autoFocus
            className="w-36 rounded border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleSave}
            disabled={!saveName.trim()}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            Save
          </button>
          <button
            onClick={() => { setShowSave(false); setSaveName(""); }}
            className="px-1.5 py-1.5 text-sm text-gray-500 hover:text-white"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Delete */}
      {isUserScreen && (
        <button
          onClick={() => { if (activeId) onDelete(activeId); }}
          className="rounded border border-gray-700 px-3 py-1.5 text-sm text-red-400/70 hover:bg-red-900/30 hover:text-red-400 transition-colors"
        >
          Delete
        </button>
      )}

      <div className="h-5 w-px bg-gray-800" />

      {hasFilters && (
        <button
          onClick={onClear}
          className="rounded px-3 py-1.5 text-sm text-gray-500 hover:text-white transition-colors"
        >
          Clear
        </button>
      )}
      <button
        onClick={onExport}
        disabled={!hasRows}
        title="Export CSV"
        className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
      </button>
    </div>
  );
}

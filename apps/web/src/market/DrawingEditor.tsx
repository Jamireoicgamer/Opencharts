// SPDX-License-Identifier: AGPL-3.0-or-later
// Placing, selecting, moving and deleting drawings on the price pane.
// Works with a mouse, a pen or a finger: one tap places a point, a tap on a
// shape selects it, and dragging a selected shape (or one of its handles)
// moves it.
import type { IChartApi } from 'lightweight-charts';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Icon } from '../workspace/Icon';
import type { DrawingLayer, Shape } from './DrawingLayer';
import {
  DRAWING_COLORS,
  DRAWING_TOOLS,
  distanceTo,
  type Drawing,
  type DrawingColor,
  type DrawingKind,
  type DrawingPoint,
  type Pixel,
} from './drawings';
import type { DrawingsApi } from './useDrawings';

interface Drag {
  id: string;
  /** Which point is moving, or every point (moving the whole shape). */
  point: number | 'all';
  from: Pixel;
  original: DrawingPoint[];
  moved: boolean;
}

const NEXT_COLOR: DrawingColor[] = ['accent', 'amber', 'blue', 'pink'];

function local(event: PointerEvent, element: HTMLElement): Pixel {
  const box = element.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);

export function DrawingEditor({
  container,
  chart,
  layer,
  store,
}: {
  container: RefObject<HTMLDivElement | null>;
  chart: RefObject<IChartApi | null>;
  layer: RefObject<DrawingLayer | null>;
  store: DrawingsApi;
}) {
  const [tool, setTool] = useState<DrawingKind | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const pending = useRef<DrawingPoint[]>([]);
  const drag = useRef<Drag | null>(null);
  const { drawings, add, change, remove, clear } = store;
  const chosen = drawings.find((d) => d.id === selected) ?? null;

  // Keep the layer showing the saved shapes and the selection.
  useEffect(() => {
    layer.current?.update({ shapes: drawings, selected });
  }, [layer, drawings, selected]);

  // While a tool is active, the chart doesn't pan or zoom under the pointer.
  useEffect(() => {
    chart.current?.applyOptions({ handleScroll: !tool, handleScale: !tool });
  }, [chart, tool]);

  const cancel = () => {
    pending.current = [];
    layer.current?.update({ draft: null });
    setTool(null);
  };

  useEffect(() => {
    const element = container.current;
    if (!element) return;

    const reset = () => {
      pending.current = [];
      layer.current?.update({ draft: null });
      setTool(null);
    };
    const place = async (kind: DrawingKind, points: DrawingPoint[]) => {
      reset();
      const color = NEXT_COLOR[drawings.length % NEXT_COLOR.length] ?? 'accent';
      const created = await add({ kind, points, color, text: kind === 'note' ? 'Note' : '' });
      if (created) setSelected(created.id);
    };

    const paneHeight = () => chart.current?.panes()[0]?.getHeight() ?? element.clientHeight;
    const toPixels = (shape: Shape) =>
      shape.points.map((p) => layer.current?.toPixel(p.t, p.price) ?? null);

    const hit = (p: Pixel, touch: boolean): { id: string; point: number | 'all' } | null => {
      const l = layer.current;
      if (!l) return null;
      const reach = touch ? 14 : 7;
      // The selected shape's handles come first.
      const current = drawings.find((d) => d.id === selected);
      if (current) {
        const handles = toPixels(current);
        const index = handles.findIndex((h) => h && Math.hypot(h.x - p.x, h.y - p.y) <= reach + 2);
        if (index >= 0) return { id: current.id, point: index };
      }
      let best: { id: string; distance: number } | null = null;
      for (const d of drawings) {
        const pixels = toPixels(d);
        if (pixels.some((x) => x == null)) continue;
        const distance = distanceTo(
          d.kind,
          pixels as Pixel[],
          p,
          (price) => l.priceToY(price),
          d.points.map((x) => x.price),
        );
        if (distance <= reach && (!best || distance < best.distance)) best = { id: d.id, distance };
      }
      return best ? { id: best.id, point: 'all' } : null;
    };

    const down = (event: PointerEvent) => {
      if (event.button !== 0) return;
      const l = layer.current;
      const p = local(event, element);
      if (!l || p.y > paneHeight()) return;
      if (tool) {
        const point = l.fromPixel(p);
        if (!point) return;
        event.preventDefault();
        event.stopPropagation();
        const spec = DRAWING_TOOLS.find((t) => t.kind === tool);
        pending.current = [...pending.current, point];
        if (pending.current.length >= (spec?.points ?? 1)) void place(tool, pending.current);
        return;
      }
      const found = hit(p, event.pointerType !== 'mouse');
      if (!found) {
        setSelected(null);
        return;
      }
      const shape = drawings.find((d) => d.id === found.id);
      if (!shape) return;
      event.preventDefault();
      event.stopPropagation();
      setSelected(found.id);
      drag.current = {
        id: found.id,
        point: found.point,
        from: p,
        original: shape.points,
        moved: false,
      };
      chart.current?.applyOptions({ handleScroll: false, handleScale: false });
      element.setPointerCapture?.(event.pointerId);
    };

    const moved = (d: Drag, p: Pixel): DrawingPoint[] | null => {
      const l = layer.current;
      if (!l) return null;
      const dx = p.x - d.from.x;
      const dy = p.y - d.from.y;
      const shape = drawings.find((x) => x.id === d.id);
      const next = d.original.map((point, i) => {
        if (d.point !== 'all' && d.point !== i) return point;
        const at = l.toPixel(point.t, point.price);
        if (!at) return point;
        const target = l.fromPixel({ x: at.x + dx, y: at.y + dy });
        if (!target) return point;
        // A horizontal level only moves up and down.
        return shape?.kind === 'hline' ? { t: point.t, price: target.price } : target;
      });
      return next;
    };

    const move = (event: PointerEvent) => {
      const l = layer.current;
      if (!l) return;
      const p = local(event, element);
      const d = drag.current;
      if (d) {
        const next = moved(d, p);
        if (!next) return;
        d.moved = d.moved || Math.hypot(p.x - d.from.x, p.y - d.from.y) > 2;
        l.update({ shapes: drawings.map((x) => (x.id === d.id ? { ...x, points: next } : x)) });
        return;
      }
      if (tool && pending.current.length === 1) {
        const point = l.fromPixel(p);
        if (!point) return;
        l.update({
          draft: {
            id: 'draft',
            kind: tool,
            points: [...pending.current, point],
            color: 'muted',
            text: '',
          },
        });
      }
    };

    const up = (event: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      drag.current = null;
      chart.current?.applyOptions({ handleScroll: !tool, handleScale: !tool });
      if (element.hasPointerCapture?.(event.pointerId))
        element.releasePointerCapture(event.pointerId);
      const next = moved(d, local(event, element));
      if (d.moved && next) void change(d.id, { points: next });
      else layer.current?.update({ shapes: drawings });
    };

    const key = (event: KeyboardEvent) => {
      if (typing(event.target)) return;
      if (event.key === 'Escape') {
        reset();
        setSelected(null);
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && selected) {
        event.preventDefault();
        void remove(selected);
        setSelected(null);
      }
    };

    element.addEventListener('pointerdown', down, { capture: true });
    element.addEventListener('pointermove', move);
    element.addEventListener('pointerup', up);
    element.addEventListener('pointercancel', up);
    document.addEventListener('keydown', key);
    return () => {
      element.removeEventListener('pointerdown', down, { capture: true });
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerup', up);
      element.removeEventListener('pointercancel', up);
      document.removeEventListener('keydown', key);
    };
  }, [container, chart, layer, tool, selected, drawings, add, change, remove]);

  const active = DRAWING_TOOLS.find((t) => t.kind === tool);
  return (
    <>
      <div className="drawing-tools" role="toolbar" aria-label="Drawing tools">
        <button
          type="button"
          className="chart-tool"
          aria-expanded={open}
          aria-label="Draw"
          title="Draw"
          onClick={() => {
            setOpen((o) => !o);
            cancel();
          }}
        >
          <Icon name="pen" />
        </button>
        {open &&
          DRAWING_TOOLS.map((t) => (
            <button
              key={t.kind}
              type="button"
              className="chart-tool"
              aria-pressed={tool === t.kind}
              aria-label={t.name}
              title={t.name}
              onClick={() => {
                pending.current = [];
                layer.current?.update({ draft: null });
                setSelected(null);
                setTool((current) => (current === t.kind ? null : t.kind));
              }}
            >
              <Icon name={t.kind} />
            </button>
          ))}
        {open && drawings.length > 0 && (
          <button
            type="button"
            className="chart-tool"
            aria-label="Remove all drawings"
            title="Remove all drawings"
            onClick={() => {
              if (window.confirm(`Remove all ${drawings.length} drawings on this chart?`)) {
                setSelected(null);
                void clear();
              }
            }}
          >
            <Icon name="trash" />
          </button>
        )}
      </div>
      {active && (
        <p className="drawing-hint" role="status">
          {active.name}: {active.hint} Esc to cancel.
        </p>
      )}
      {chosen && !active && (
        <SelectedDrawing drawing={chosen} store={store} onDone={() => setSelected(null)} />
      )}
      {store.error && (
        <p className="drawing-hint error" role="alert">
          {store.error}
        </p>
      )}
    </>
  );
}

function SelectedDrawing({
  drawing,
  store,
  onDone,
}: {
  drawing: Drawing;
  store: DrawingsApi;
  onDone: () => void;
}) {
  const [text, setText] = useState(drawing.text);
  const name = DRAWING_TOOLS.find((t) => t.kind === drawing.kind)?.name ?? 'Drawing';
  const save = () => {
    if (text !== drawing.text) void store.change(drawing.id, { text: text.slice(0, 200) });
  };
  return (
    <div className="drawing-selected" role="group" aria-label={`Selected ${name.toLowerCase()}`}>
      <span className="muted">{name}</span>
      <div className="swatches" role="radiogroup" aria-label="Colour">
        {DRAWING_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            role="radio"
            aria-checked={drawing.color === c}
            aria-label={c}
            className="swatch"
            data-color={c}
            onClick={() => void store.change(drawing.id, { color: c })}
          />
        ))}
      </div>
      {drawing.kind !== 'trend' && drawing.kind !== 'fib' && (
        <input
          aria-label="Label"
          placeholder="Label"
          maxLength={200}
          value={text}
          autoFocus={drawing.kind === 'note'}
          onChange={(e) => setText(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              save();
              (e.target as HTMLInputElement).blur();
            }
          }}
        />
      )}
      <button
        type="button"
        className="icon-button small"
        aria-label={`Delete ${name.toLowerCase()}`}
        onClick={() => {
          void store.remove(drawing.id);
          onDone();
        }}
      >
        <Icon name="trash" />
      </button>
    </div>
  );
}

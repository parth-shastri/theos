"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Glass, Icon } from "./Primitives";

const iso = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const parse = (value) =>
  /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(value + "T12:00:00")
    : new Date();
const monthStart = (date) =>
  new Date(date.getFullYear(), date.getMonth(), 1, 12);
export default function OpenUIDatePicker({
  id,
  label,
  value,
  onChange,
  disabled,
}) {
  const [open, setOpen] = useState(false),
    [month, setMonth] = useState(() => monthStart(parse(value))),
    [focused, setFocused] = useState(() => iso(parse(value))),
    [position, setPosition] = useState({});
  const trigger = useRef(null),
    menu = useRef(null),
    input = useRef(null);
  const close = (focus = false) => {
    setOpen(false);
    if (focus) trigger.current?.focus();
  };
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  useLayoutEffect(() => {
    if (!open) return;
    if (!menu.current?.showPopover) {
      input.current?.showPicker?.();
      setOpen(false);
      return;
    }
    const menuElement = menu.current;
    const rect = trigger.current.parentElement.getBoundingClientRect(),
      width = Math.min(304, innerWidth - 24),
      above = rect.top > 380;
    setPosition({
      width,
      left: Math.max(12, Math.min(rect.left, innerWidth - width - 12)),
      top: above
        ? Math.max(12, rect.top - 360)
        : Math.min(rect.bottom + 8, innerHeight - 360),
    });
    menuElement.showPopover();
    menu.current
      .querySelector('[tabindex="0"]')
      ?.focus({ preventScroll: true });
    const outside = (event) => {
      if (
        !menu.current?.contains(event.target) &&
        !trigger.current?.contains(event.target)
      )
        close();
    };
    const scroll = (event) => {
      if (!menu.current?.contains(event.target)) close();
    };
    const resize = () => close();
    document.addEventListener("pointerdown", outside);
    document.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", resize);
    return () => {
      if (menuElement.matches(":popover-open")) menuElement.hidePopover();
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]);
  const move = (date) => {
    setMonth(monthStart(date));
    setFocused(iso(date));
    requestAnimationFrame(() =>
      menu.current
        ?.querySelector(`[data-date="${iso(date)}"]`)
        ?.focus({ preventScroll: true }),
    );
  };
  const keys = (event, date) => {
    const offsets = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
      Home: -((date.getDay() + 6) % 7),
      End: 6 - ((date.getDay() + 6) % 7),
    };
    if (event.key in offsets) {
      event.preventDefault();
      move(
        new Date(
          date.getFullYear(),
          date.getMonth(),
          date.getDate() + offsets[event.key],
          12,
        ),
      );
    } else if (event.key === "PageUp" || event.key === "PageDown") {
      event.preventDefault();
      move(
        new Date(
          date.getFullYear(),
          date.getMonth() + (event.key === "PageDown" ? 1 : -1),
          1,
          12,
        ),
      );
    }
  };
  const first = (month.getDay() + 6) % 7,
    days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  return (
    <div className="openui-date-field">
      <label htmlFor={id}>{label}</label>
      <div className="openui-date-input">
        <input
          ref={input}
          id={id}
          name="reminder_date"
          type="date"
          value={value}
          required
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          ref={trigger}
          type="button"
          className="icon-button"
          aria-label="Choose reminder date"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={id + "-calendar"}
          disabled={disabled}
          onClick={() => {
            if (!open) {
              setMonth(monthStart(parse(value)));
              setFocused(iso(parse(value)));
            }
            setOpen(!open);
          }}
        >
          <Icon name="calendar" />
        </button>
      </div>
      <Glass
        ref={menu}
        id={id + "-calendar"}
        className="openui-calendar settings-select-menu"
        role="dialog"
        aria-label="Choose reminder date"
        popover="manual"
        style={position}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            close(true);
          }
        }}
      >
        <div className="openui-calendar-heading">
          <button
            type="button"
            className="icon-button"
            aria-label="Previous month"
            onClick={() =>
              move(new Date(month.getFullYear(), month.getMonth() - 1, 1, 12))
            }
          >
            <Icon name="back" />
          </button>
          <strong aria-live="polite">
            {month.toLocaleDateString(undefined, {
              month: "long",
              year: "numeric",
            })}
          </strong>
          <button
            type="button"
            className="icon-button openui-next-month"
            aria-label="Next month"
            onClick={() =>
              move(new Date(month.getFullYear(), month.getMonth() + 1, 1, 12))
            }
          >
            <Icon name="back" />
          </button>
        </div>
        <div className="openui-calendar-week" aria-hidden="true">
          {["M", "T", "W", "T", "F", "S", "S"].map((day, i) => (
            <span key={i}>{day}</span>
          ))}
        </div>
        <div className="openui-calendar-grid" role="group" aria-label="Days">
          {Array.from({ length: first + days }, (_, i) => {
            if (i < first) return <span key={i} />;
            const date = new Date(
                month.getFullYear(),
                month.getMonth(),
                i - first + 1,
                12,
              ),
              day = iso(date);
            return (
              <button
                type="button"
                key={day}
                data-date={day}
                aria-label={date.toLocaleDateString(undefined, {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
                aria-pressed={day === value}
                aria-current={day === iso(new Date()) ? "date" : undefined}
                tabIndex={day === focused ? 0 : -1}
                onKeyDown={(e) => keys(e, date)}
                onClick={() => {
                  onChange(day);
                  close(true);
                }}
              >
                {date.getDate()}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="openui-calendar-today"
          onClick={() => {
            onChange(iso(new Date()));
            close(true);
          }}
        >
          Choose today
        </button>
      </Glass>
    </div>
  );
}

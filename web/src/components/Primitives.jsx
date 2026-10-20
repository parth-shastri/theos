"use client";
import {
  createContext,
  forwardRef,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { iconPaths, providerIcons } from "../state/config";
import { createGlass } from "../runtime/glass";
import { createScope } from "../runtime/scope";

export function Icon({ name, className }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      fill={name === "stop" ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={
        className || (name === "loading" ? "voice-spinner" : undefined)
      }
    >
      {iconPaths[name].map((d) => (
        <path d={d} key={d} />
      ))}
    </svg>
  );
}
export function ConnectionIcon({ id }) {
  if (providerIcons[id])
    return (
      <img
        src={providerIcons[id]}
        alt=""
        className="provider-icon"
        width="32"
        height="32"
      />
    );
  const names = {
    sandbox: "sandbox",
    memory: "memory",
    search: "search",
    storage: "storage",
    transcription: "transcription",
    tts: "speaker",
    weather: "weather",
    skills: "skills",
  };
  return (
    <span className="service-icon" aria-hidden="true">
      <Icon name={names[id] || "connection"} />
    </span>
  );
}
const GlassContext = createContext(null);
export function GlassProvider({ children }) {
  const effects = useRef(null);
  useLayoutEffect(() => {
    const scope = createScope();
    effects.current = createGlass(scope);
    return () => {
      scope.dispose();
      effects.current = null;
    };
  }, []);
  return (
    <GlassContext.Provider value={effects}>{children}</GlassContext.Provider>
  );
}
export const Glass = forwardRef(function Glass(
  { as: Tag = "div", children, className = "", ...props },
  forwardedRef,
) {
  const element = useRef(null);
  const effects = useContext(GlassContext);
  useLayoutEffect(() => {
    const surface = element.current;
    return () => effects?.current?.release(surface);
  }, [effects]);
  useLayoutEffect(() => {
    if (element.current) effects?.current?.enhance(element.current);
  });
  return (
    <Tag
      {...props}
      className={className}
      ref={(value) => {
        element.current = value;
        if (typeof forwardedRef === "function") forwardedRef(value);
        else if (forwardedRef) forwardedRef.current = value;
      }}
    >
      <span className="glass-optics" aria-hidden="true" />
      {Tag === "aside" || Tag === "dialog" ? (
        <div className="glass-content">{children}</div>
      ) : (
        children
      )}
    </Tag>
  );
});
export function Dialog({ id, open, onClose, children, saving, ...props }) {
  const ref = useRef(null);
  const previous = useRef(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
    previous.current = open;
  }, [open]);
  return (
    <Glass
      as="dialog"
      id={id}
      ref={ref}
      {...props}
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onClose();
      }}
      onClose={() => {
        if (previous.current && !saving) onClose();
      }}
    >
      {children}
    </Glass>
  );
}
export function SelectPicker({
  id,
  label,
  value,
  options,
  onChange,
  icon,
  disabled,
  describedBy,
}) {
  const [enhanced, setEnhanced] = useState(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({});
  const trigger = useRef(null),
    menu = useRef(null),
    list = useRef(null);
  const typed = useRef({ text: "", at: 0 });
  const close = (focus = false) => {
    setOpen(false);
    if (focus) trigger.current?.focus();
  };
  useEffect(() => {
    setEnhanced(!!HTMLElement.prototype.showPopover);
  }, []);
  useLayoutEffect(() => {
    if (!open || disabled || !options.length) return;
    const bounds = window.visualViewport,
      rect = trigger.current.getBoundingClientRect();
    const top = bounds?.offsetTop || 0,
      left = bounds?.offsetLeft || 0;
    const height = bounds?.height || innerHeight,
      width = bounds?.width || innerWidth;
    const above = rect.top - top - 16,
      below = top + height - rect.bottom - 16;
    const desired = Math.min(394, options.length * 48 + 10);
    const upward = above >= desired || above > below;
    let menuHeight = Math.max(44, Math.min(desired, upward ? above : below));
    if (menuHeight < desired && menuHeight >= 58)
      menuHeight = Math.floor((menuHeight - 10) / 48) * 48 + 10;
    const menuWidth = Math.min(rect.width, width - 24);
    setPosition({
      width: menuWidth,
      maxHeight: menuHeight,
      left: Math.min(
        Math.max(left + 12, rect.left),
        left + width - menuWidth - 12,
      ),
      top: upward ? rect.top - menuHeight - 8 : rect.bottom + 8,
      upward,
    });
    menu.current.showPopover();
    const selected =
      menu.current.querySelector('[aria-selected="true"]:not(:disabled)') ||
      menu.current.querySelector("button:not(:disabled)");
    selected?.focus({ preventScroll: true });
    selected?.scrollIntoView({ block: "nearest" });
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
    window.visualViewport?.addEventListener("resize", resize);
    return () => {
      if (menu.current?.matches(":popover-open")) menu.current.hidePopover();
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, [open, disabled, options]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  const keydown = (event) => {
    const choices = [...menu.current.querySelectorAll("button:not(:disabled)")];
    const index = choices.indexOf(document.activeElement);
    if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? choices.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + choices.length) %
              choices.length;
      choices[next]?.focus({ preventScroll: true });
      choices[next]?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") close(true);
    else if (
      event.key.length === 1 &&
      event.key !== " " &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      const now = performance.now();
      typed.current = {
        text:
          (now - typed.current.at < 650 ? typed.current.text : "") +
          event.key.toLowerCase(),
        at: now,
      };
      choices
        .find((option) =>
          option.textContent.toLowerCase().startsWith(typed.current.text),
        )
        ?.focus();
    }
  };
  const selectedLabel =
    options.find((option) => option.value === value)?.label || "Choose…";
  return (
    <>
      <label htmlFor={enhanced ? id + "-trigger" : id}>{label}</label>
      <select
        id={id}
        hidden={enhanced}
        value={value}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option
            value={option.value}
            disabled={option.disabled}
            key={option.value}
          >
            {option.label}
          </option>
        ))}
      </select>
      {enhanced && (
        <>
          <button
            type="button"
            id={id + "-trigger"}
            className="settings-select-trigger"
            ref={trigger}
            disabled={disabled || !options.length}
            aria-label={label + ": " + selectedLabel}
            aria-describedby={describedBy || ""}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={id + "-menu"}
            onClick={() => setOpen(!open)}
            onKeyDown={(event) => {
              if (["ArrowUp", "ArrowDown"].includes(event.key)) {
                event.preventDefault();
                setOpen(true);
              }
            }}
          >
            <Icon name={icon} />
            <span className="settings-select-value">{selectedLabel}</span>
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              className="select-chevron"
            >
              <path d="m7 10 5 5 5-5" />
            </svg>
          </button>
          <Glass
            id={id + "-menu"}
            className={
              "settings-select-menu" + (position.upward ? " opens-up" : "")
            }
            popover="manual"
            role="listbox"
            aria-label={label}
            ref={menu}
            style={{
              width: position.width,
              maxHeight: position.maxHeight,
              left: position.left,
              top: position.top,
            }}
            onKeyDown={keydown}
          >
            <div
              className="settings-select-options"
              ref={list}
              style={{
                maxHeight: Math.max(30, (position.maxHeight || 44) - 14),
              }}
            >
              {options.map((option) => (
                <button
                  type="button"
                  role="option"
                  className="settings-select-option"
                  tabIndex={-1}
                  aria-selected={option.value === value}
                  disabled={option.disabled}
                  key={option.value}
                  onClick={() => {
                    onChange(option.value);
                    close(true);
                  }}
                >
                  <span>{option.label}</span>
                  <Icon name="check" />
                </button>
              ))}
            </div>
          </Glass>
        </>
      )}
    </>
  );
}

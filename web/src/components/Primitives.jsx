"use client";
import {
  createContext,
  forwardRef,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { providerIcons } from "../state/config";
import { Icon } from "./Icon.js";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { createGlass } from "../runtime/glass";
import { createScope } from "../runtime/scope";

export { Icon };
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
    calendar: "calendar",
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
  const trigger = useRef(null);
  const [open, setOpen] = useState(false);
  const [container, setContainer] = useState(null);
  const selectedLabel = options.find((option) => option.value === value)?.label;
  return (
    <>
      <label htmlFor={id + "-trigger"}>{label}</label>
      <Select
        value={value}
        onValueChange={onChange}
        disabled={disabled || !options.length}
        open={open}
        onOpenChange={(next) => {
          if (next)
            setContainer(trigger.current?.closest("dialog") || document.body);
          setOpen(next);
        }}
      >
        <SelectTrigger
          id={id + "-trigger"}
          ref={trigger}
          aria-label={`${label}: ${selectedLabel || "Choose…"}`}
          aria-describedby={describedBy}
          className="settings-select-trigger"
        >
          {icon && <Icon name={icon} />}
          <SelectValue placeholder="Choose…" />
        </SelectTrigger>
        <SelectContent
          id={id + "-menu"}
          container={container}
          position="popper"
          align="start"
          sideOffset={8}
          className="settings-select-menu"
        >
          {options.map((option) => (
            <SelectItem
              value={option.value}
              disabled={option.disabled}
              className="settings-select-option"
              key={option.value}
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </>
  );
}

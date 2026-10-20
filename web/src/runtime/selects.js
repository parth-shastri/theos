// Native select elements remain the source of truth for settings validation.
export function createSelects(scope) {
  const pickers = new Map();
  let active = null;
  function close(restoreFocus = false) {
    if (!active) return;
    const picker = active;
    active = null;
    if (picker.menu.matches(":popover-open")) picker.menu.hidePopover();
    picker.trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus) picker.trigger.focus();
  }
  function sync(id) {
    const picker = pickers.get(id);
    if (!picker) return;
    const { select, trigger, value } = picker;
    value.textContent = select.selectedOptions[0]?.textContent || "Choose…";
    trigger.disabled = select.disabled || !select.options.length;
    trigger.setAttribute("aria-label", `${picker.label}: ${value.textContent}`);
    if (trigger.disabled && active === picker) close();
  }
  function focusOption(picker, option) {
    if (!option) return;
    option.focus({
      preventScroll: true,
    });
    const { list } = picker;
    const top = option.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + option.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = top + option.offsetHeight - list.clientHeight;
  }
  function open(picker) {
    const { select, trigger, menu, list, check } = picker;
    if (select.disabled || !select.options.length) return;
    close();
    list.replaceChildren();
    const options = [...select.options].map((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "option";
      button.className = "settings-select-option";
      button.tabIndex = -1;
      button.disabled = option.disabled;
      button.setAttribute("aria-selected", String(option.selected));
      const label = document.createElement("span");
      label.textContent = option.textContent;
      button.append(label, check.cloneNode(true));
      button.onclick = () => {
        select.value = option.value;
        close(true);
        select.dispatchEvent(
          new Event("change", {
            bubbles: true,
          }),
        );
        sync(select.id);
      };
      list.append(button);
      return button;
    });
    picker.options = options;
    const bounds = window.visualViewport;
    const viewTop = bounds?.offsetTop || 0;
    const viewLeft = bounds?.offsetLeft || 0;
    const viewHeight = bounds?.height || innerHeight;
    const viewWidth = bounds?.width || innerWidth;
    const rect = trigger.getBoundingClientRect();
    const above = rect.top - viewTop - 16;
    const below = viewTop + viewHeight - rect.bottom - 16;
    const desired = Math.min(394, options.length * 48 + 10);
    const upward = above >= desired || above > below;
    let height = Math.max(44, Math.min(desired, upward ? above : below));
    // Keep complete rows visible when a short screen requires scrolling.
    if (height < desired && height >= 58)
      height = Math.floor((height - 10) / 48) * 48 + 10;
    const width = Math.min(rect.width, viewWidth - 24);
    const left = Math.min(
      Math.max(viewLeft + 12, rect.left),
      viewLeft + viewWidth - width - 12,
    );
    menu.style.width = `${width}px`;
    menu.style.maxHeight = `${height}px`;
    list.style.maxHeight = `${Math.max(30, height - 14)}px`;
    menu.style.left = `${left}px`;
    menu.style.top = `${upward ? rect.top - height - 8 : rect.bottom + 8}px`;
    menu.classList.toggle("opens-up", upward);
    active = picker;
    trigger.setAttribute("aria-expanded", "true");
    menu.showPopover();
    focusOption(
      picker,
      options.find(
        (option) =>
          option.getAttribute("aria-selected") === "true" && !option.disabled,
      ) || options.find((option) => !option.disabled),
    );
  }
  function enhance(select, icon, check) {
    // Keep a working native picker in browsers without top-layer popovers.
    if (!HTMLElement.prototype.showPopover) return;
    const label = document.querySelector(`label[for="${select.id}"]`);
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = `${select.id}-trigger`;
    trigger.className = "settings-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", `${select.id}-menu`);
    trigger.setAttribute(
      "aria-describedby",
      select.getAttribute("aria-describedby") || "",
    );
    const value = document.createElement("span");
    value.className = "settings-select-value";
    const arrow = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    arrow.setAttribute("viewBox", "0 0 24 24");
    arrow.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(arrow.namespaceURI, "path");
    path.setAttribute("d", "m7 10 5 5 5-5");
    arrow.append(path);
    arrow.classList.add("select-chevron");
    trigger.append(icon, value, arrow);
    const menu = document.createElement("div");
    menu.id = `${select.id}-menu`;
    menu.className = "settings-select-menu";
    menu.popover = "manual";
    menu.role = "listbox";
    menu.setAttribute("aria-label", label.textContent);
    const list = document.createElement("div");
    list.className = "settings-select-options";
    menu.append(list);
    select.after(trigger, menu);
    select.hidden = true;
    label.htmlFor = trigger.id;
    const picker = {
      select,
      trigger,
      menu,
      list,
      check,
      value,
      label: label.textContent,
      options: [],
    };
    pickers.set(select.id, picker);
    trigger.onclick = () => (active === picker ? close() : open(picker));
    trigger.onkeydown = (event) => {
      if (["ArrowUp", "ArrowDown"].includes(event.key)) {
        event.preventDefault();
        open(picker);
      }
    };
    let typed = "",
      typedAt = 0;
    menu.onkeydown = (event) => {
      const choices = picker.options.filter((option) => !option.disabled);
      const current = choices.indexOf(document.activeElement);
      if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? choices.length - 1
              : (current +
                  (event.key === "ArrowDown" ? 1 : -1) +
                  choices.length) %
                choices.length;
        focusOption(picker, choices[next]);
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
        typed = (now - typedAt < 650 ? typed : "") + event.key.toLowerCase();
        typedAt = now;
        focusOption(
          picker,
          choices.find((option) =>
            option.textContent.toLowerCase().startsWith(typed),
          ),
        );
      }
    };
    scope.listen(menu, "toggle", (event) => {
      if (event.newState === "closed") {
        trigger.setAttribute("aria-expanded", "false");
        if (active === picker) active = null;
      }
    });
    scope.observe(new MutationObserver(() => sync(select.id))).observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled"],
    });
    scope.listen(select, "change", () => sync(select.id));
    sync(select.id);
  }
  scope.listen(document, "pointerdown", (event) => {
    if (
      active &&
      !active.menu.contains(event.target) &&
      !active.trigger.contains(event.target)
    )
      close();
  });
  scope.listen(
    document,
    "scroll",
    (event) => {
      if (active && !active.menu.contains(event.target)) close();
    },
    true,
  );
  scope.listen(window, "resize", () => close());
  scope.listen(window.visualViewport, "resize", () => close());
  scope.onDispose(() => {
    close();
    for (const { select, trigger, menu } of pickers.values()) {
      const label = document.querySelector('label[for="' + trigger.id + '"]');
      if (label) label.htmlFor = select.id;
      select.hidden = false;
      trigger.remove();
      menu.remove();
    }
    pickers.clear();
  });
  return {
    enhance,
    sync,
    close,
  };
}

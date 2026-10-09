"""Deployment settings and usage screens for the terminal client."""

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

PARAMETER_LABELS = {
    "max_output_tokens": "Output token limit",
    "temperature": "Temperature",
    "top_p": "Top P",
    "top_k": "Top K",
    "seed": "Seed",
    "frequency_penalty": "Frequency penalty",
    "presence_penalty": "Presence penalty",
}
INTEGER_PARAMETERS = {"max_output_tokens", "top_k", "seed"}


class SettingsScreen(ModalScreen[bool]):
    """Save one draft through the server's existing settings validation."""

    CSS = """
    SettingsScreen { align: center middle; background: #000000 60%; }
    #settings-panel { width: 76; max-width: 95%; height: auto; max-height: 90%;
        border: round #79b8ff; background: #0d0f12; padding: 1 2; }
    #settings-fields { height: auto; max-height: 24; }
    #settings-panel Label { margin-top: 1; }
    #settings-panel Select, #settings-panel Input { height: 3; }
    #settings-title { text-style: bold; color: #79b8ff; }
    #settings-actions { height: 3; margin-top: 1; align-horizontal: right; }
    #settings-error { color: #ff8080; height: auto; }
    #settings-generation { height: auto; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, session, session_id, configuration, *, focus=""):
        super().__init__()
        self.session = session
        self.session_id = session_id
        self.configuration = configuration
        self.focus_field = focus
        self.values = dict(configuration["session"]["generation"])
        self.saving = False

    def capabilities(self, model):
        return self.configuration["catalog"]["generation_capabilities"][model]

    def compose(self):
        row = self.configuration["session"]
        models = self.configuration["catalog"]["models"]
        choices = self.capabilities(row["model"])["reasoning"]
        with Container(id="settings-panel"):
            yield Static("Conversation settings", id="settings-title")
            yield Static(row["title"], markup=False)
            with VerticalScroll(id="settings-fields"):
                yield Label("Model")
                yield Select(
                    [(value, value) for value in models],
                    value=row["model"],
                    allow_blank=False,
                    id="settings-model",
                )
                yield Label("Reasoning effort")
                yield Select(
                    [(value.title(), value) for value in choices],
                    value=row["reasoning"],
                    allow_blank=False,
                    id="settings-reasoning",
                )
                yield Label("Generation parameters · blank uses the model default")
                yield Container(id="settings-generation")
            yield Static("", id="settings-error", markup=False)
            with Horizontal(id="settings-actions"):
                yield Button("Cancel", id="settings-cancel")
                yield Button("Save settings", id="settings-save", variant="primary")

    async def on_mount(self):
        await self.render_parameters(self.query_one("#settings-model", Select).value)
        self.query_one("#settings-" + (self.focus_field or "model"), Select).focus()

    def collect_parameters(self):
        return {
            widget.name: widget.value.strip() for widget in self.query("#settings-generation Input")
        }

    async def render_parameters(self, model):
        container = self.query_one("#settings-generation", Container)
        await container.remove_children()
        for key in self.capabilities(model)["parameters"]:
            value = self.values.get(key, "")
            if key == "max_output_tokens" and value != "":
                try:
                    value = min(int(value), self.capabilities(model)["max_output_tokens"])
                except ValueError:
                    pass
            await container.mount(
                Label(PARAMETER_LABELS[key]),
                Input(str(value), name=key, id="parameter-" + key, placeholder="Model default"),
            )

    async def on_select_changed(self, event: Select.Changed):
        if event.select.id != "settings-model" or event.value is Select.BLANK:
            return
        if not self.is_mounted:
            return
        self.values.update(self.collect_parameters())
        reasoning = self.query_one("#settings-reasoning", Select)
        previous = reasoning.value
        choices = self.capabilities(event.value)["reasoning"]
        reasoning.set_options([(value.title(), value) for value in choices])
        reasoning.value = previous if previous in choices else "default"
        await self.render_parameters(event.value)

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "settings-cancel":
            return self.action_cancel()
        if event.button.id != "settings-save" or self.saving:
            return
        try:
            values = {}
            for key, value in self.collect_parameters().items():
                if value:
                    values[key] = int(value) if key in INTEGER_PARAMETERS else float(value)
        except ValueError:
            self.query_one("#settings-error", Static).update(
                "Enter valid numbers or leave parameter fields empty."
            )
            return
        self.saving = True
        for widget in self.query("Button, Input, Select"):
            widget.disabled = True
        try:
            await self.session.save_settings(
                self.session_id,
                self.query_one("#settings-model", Select).value,
                self.query_one("#settings-reasoning", Select).value,
                values,
            )
        except (ValueError, LookupError, RuntimeError) as error:
            self.query_one("#settings-error", Static).update(str(error))
        else:
            self.dismiss(True)
        finally:
            self.saving = False
            for widget in self.query("Button, Input, Select"):
                widget.disabled = False

    def action_cancel(self):
        if not self.saving:
            self.dismiss(False)


class UsageScreen(ModalScreen):
    CSS = """
    UsageScreen { align: center middle; background: #000000 60%; }
    #usage-panel { width: 72; max-width: 95%; height: auto; max-height: 90%;
        border: round #79b8ff; background: #0d0f12; padding: 1 2; }
    #usage-content { height: auto; max-height: 28; }
    #usage-panel Button { margin-top: 1; }
    """
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, usage):
        super().__init__()
        self.usage = usage

    def compose(self):
        sections = []
        for key, title in [
            ("conversation", "This conversation"),
            ("total", "Your total across transports"),
        ]:
            row = self.usage[key]
            cost = (
                "$0.00"
                if not row["requests"]
                else "Unavailable"
                if row["cost"] is None
                else f"${row['cost']:.6f}"
            )
            if row["unpriced_requests"] and row["cost"] is not None:
                cost += " (partial)"
            table = Table.grid(padding=(0, 3))
            table.add_column()
            table.add_column(justify="right")
            table.add_row("Cost · USD", cost)
            for label, field in [
                ("Requests", "requests"),
                ("Input tokens", "input_tokens"),
                ("Output tokens", "output_tokens"),
                ("Unpriced requests", "unpriced_requests"),
            ]:
                table.add_row(label, f"{row[field]:,}")
            sections.extend([Text(title, style="bold cyan"), table, Text("")])
        sections.append(
            Text(
                "Costs use reported amounts or configured estimates.\nRequests without a recorded price remain visible.",
                style="dim",
            )
        )
        with Container(id="usage-panel"):
            with VerticalScroll(id="usage-content"):
                yield Static(Group(*sections))
            yield Button("Close", id="usage-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        self.action_close()

    def action_close(self):
        self.dismiss()

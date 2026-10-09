"""Theos startup approvals and background notices around the generic terminal UI."""

from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from renderer.interactive import await_if_needed
from renderer.tui import HarnessTui

REMOTE_COMMANDS = (
    ("/settings", "Edit deployment model, reasoning, and generation settings"),
    ("/model", "Choose an available deployment model"),
    ("/reasoning", "Choose supported reasoning effort"),
    ("/usage", "Show conversation and user costs and tokens"),
    ("/continue", "Continue saved work after an interruption"),
)


class TheosTui(HarnessTui):
    """Keep application background delivery outside the generic renderer."""

    def __init__(self, session, **kwargs):
        super().__init__(session, **kwargs)
        self.remote = hasattr(session, "configuration")
        if self.remote:
            self.command_specs = (*self.command_specs, *REMOTE_COMMANDS)
            self.commands_with_argument = self.commands_with_argument | {"/model", "/reasoning"}

    async def _command(self, raw):
        command, _, argument = raw.partition(" ")
        command = command.lower()
        if not self.remote or command not in {
            "/settings",
            "/model",
            "/reasoning",
            "/usage",
            "/help",
            "/continue",
        }:
            try:
                return await super()._command(raw)
            except (ValueError, LookupError, RuntimeError) as error:
                self.notify(str(error), severity="error")
                return
        if command == "/help":
            self.renderer.command_guide((("DEPLOYMENT", REMOTE_COMMANDS),))
            return
        if command in {"/settings", "/usage", "/continue"} and argument.strip():
            self.notify(f"{command} takes no arguments.", severity="warning")
            return
        if command != "/usage" and self._busy:
            self.notify("Wait for the running turn before you change settings.", severity="warning")
            return
        try:
            if command == "/continue":
                self.run_turn(None)
                return
            if command == "/usage":
                from .screens import UsageScreen

                self.push_screen(UsageScreen(await self.session.usage(self.session_id)))
                return
            if command == "/settings":
                from .screens import SettingsScreen

                self.push_screen(
                    SettingsScreen(
                        self.session,
                        self.session_id,
                        await self.session.configuration(self.session_id),
                    ),
                    self._settings_closed,
                )
                return
            if not argument.strip():
                prompt = self.query_one("#prompt", Input)
                prompt.value = command + " "
                prompt.cursor_position = len(prompt.value)
                self._refresh_command_menu(prompt.value)
                prompt.focus()
                return
            config = await self.session.configuration(self.session_id)
            row, catalog = config["session"], config["catalog"]
            model = argument.strip() if command == "/model" else row["model"]
            if model not in catalog["models"]:
                raise ValueError("Choose a model from the command options.")
            capabilities = catalog["generation_capabilities"][model]
            reasoning = argument.strip() if command == "/reasoning" else row["reasoning"]
            if reasoning not in capabilities["reasoning"]:
                if command == "/reasoning":
                    raise ValueError("Choose reasoning effort from the command options.")
                reasoning = "default"
            generation = {
                key: value
                for key, value in row["generation"].items()
                if key in capabilities["parameters"]
            }
            if "max_output_tokens" in generation:
                generation["max_output_tokens"] = min(
                    generation["max_output_tokens"], capabilities["max_output_tokens"]
                )
            await self.session.save_settings(self.session_id, model, reasoning, generation)
            await self._refresh_settings_status()
        except (ValueError, LookupError, RuntimeError) as error:
            self.notify(str(error), severity="error")

    def _settings_closed(self, saved):
        if saved:
            self.run_worker(self._refresh_settings_status(), group="settings")

    async def _refresh_settings_status(self):
        self.runtime_info = await self._load_runtime_info()
        self.renderer.runtime_info = self.runtime_info
        self.renderer._set_status("settings saved")
        self.notify("Settings saved on the deployment.")

    def _refresh_command_menu(self, value):
        name, separator, argument = value.partition(" ")
        if not self.remote or not separator or name.lower() not in {"/model", "/reasoning"}:
            return super()._refresh_command_menu(value)
        name = name.lower()
        model = self.runtime_info.model
        values = (
            self.session.me["models"]
            if name == "/model"
            else self.session.me["generation_capabilities"][model]["reasoning"]
        )
        self._menu_mode = "commands"
        self._visible_files = []
        self._visible_commands = [
            (name + " " + choice, "Choose " + name[1:])
            for choice in values
            if choice.lower().startswith(argument.lower())
        ]
        menu = self.query_one("#command-menu", OptionList)
        menu.clear_options()
        for index, (choice, description) in enumerate(self._visible_commands):
            menu.add_option(Option(choice + "  · " + description, id=f"command-{index}"))
        menu.display = bool(self._visible_commands)
        menu.highlighted = 0 if self._visible_commands else None

    def _complete_command(self, command):
        super()._complete_command(command)
        if self.remote and command in {"/model", "/reasoning"}:
            self._refresh_command_menu(command + " ")

    async def on_input_submitted(self, event: Input.Submitted):
        # Textual dispatches handlers through the MRO. Invoke the base handler once.
        event.prevent_default()
        if (
            self.remote
            and event.value.partition(" ")[0].lower() in {"/model", "/reasoning"}
            and " " in event.value
            and self._visible_commands
        ):
            self._complete_highlighted_suggestion()
            return
        await super().on_input_submitted(event)

    async def on_mount(self, event):
        event.prevent_default()
        initial = self.initial_prompt is not None or bool(self._attachments)
        await super().on_mount()
        self.set_interval(1, self._poll_notices)
        if not initial and not self.open_session_picker:
            await self._restore_approvals()

    async def _restore_approvals(self):
        if not self._busy and await await_if_needed(
            self.session.pending_interactions(self.session_id)
        ):
            self.run_turn(None)

    async def _switch_existing_session(self, session_id):
        await super()._switch_existing_session(session_id)
        await self._restore_approvals()

    async def _poll_notices(self):
        try:
            for row in await await_if_needed(self.session.notifications()):
                title = await await_if_needed(self.session.session_title(row["session"]))
                self.renderer.note(f"Notification · {title}\n{row['text']}")
                if row["session"] == self.session_id:
                    await self._restore_approvals()
            self._notice_error = False
        except (ValueError, LookupError, RuntimeError) as error:
            if not getattr(self, "_notice_error", False):
                self.notify(str(error), severity="warning")
            self._notice_error = True

"""Separate call allowances under one turn ceiling."""

from math import ceil, inf

from harness import Budget


class CallAllowance(Budget):
    """Charge the local allowance and the shared ceiling before each request."""

    def __init__(self, maximum, total):
        super().__init__(maximum)
        self.total = total
        self.held = 0

    def spend(self):
        if self.used >= self.max_model_calls - self.held or not self.total.spend():
            return False
        self.used += 1
        return True

    def reserve(self):
        """Hold a response call before research can consume it."""
        if self.used + self.held >= self.max_model_calls:
            return None
        self.held += 1
        return ReservedCall(self)


class ReservedCall(Budget):
    """One held call. Other research cannot spend it."""

    def __init__(self, allowance):
        super().__init__(1)
        self.allowance = allowance
        self.held = True

    def spend(self):
        if not self.held:
            return False
        self.release()
        if not self.allowance.spend():
            return False
        self.used = 1
        return True

    def release(self):
        if self.held:
            self.allowance.held -= 1
            self.held = False


class FinalSummaryBudget:
    """Use a held summary call, then any unheld summary calls still available."""

    def __init__(self, allowance, reserved):
        self.allowance = allowance
        self.reserved = reserved
        self.used = 0

    @property
    def max_model_calls(self):
        remaining = self.allowance.max_model_calls - self.allowance.used - self.allowance.held
        return self.used + remaining + int(bool(self.reserved and self.reserved.held))

    def spend(self):
        if self.reserved and self.reserved.held:
            spent = self.reserved.spend()
        else:
            spent = self.allowance.spend()
        if spent:
            self.used += 1
        return spent

    def release(self):
        if self.reserved:
            self.reserved.release()


class TurnBudget:
    """Keep research, compaction, and recovery within the configured total."""

    def __init__(self, settings, *, enforce=True):
        self.enforced = enforce
        # Theos runs long tasks without call allocations. Keep the configuration
        # and bounded mode for other callers, but count every call in both modes.
        if not enforce:
            self.total = Budget(inf)
            self.research = CallAllowance(inf, self.total)
            self.compaction = CallAllowance(inf, self.total)
            self.recovery = CallAllowance(inf, self.total)
            self.delegate_limit = inf
            self.final_compaction = self.reserve_final_summary()
            return
        self.total = Budget(settings.max_model_calls)
        final = 1
        # Resolve once per turn. An explicit zero disables summaries rather than using the ratio.
        requested_summaries = settings.max_compaction_calls
        if requested_summaries is None:
            requested_summaries = ceil(settings.max_model_calls * settings.compaction_call_ratio)
        # Small ceilings retain one research call before allocating compaction.
        compact = min(requested_summaries, max(0, settings.max_model_calls - final - 1))
        self.research = CallAllowance(settings.max_model_calls - compact - final, self.total)
        self.compaction = CallAllowance(compact, self.total)
        requested_delegate = settings.delegate_max_model_calls
        if requested_delegate is None:
            requested_delegate = ceil(settings.max_model_calls * settings.delegate_call_ratio)
        # The delegate ceiling includes its handoff. Summaries use the separate shared pool.
        self.delegate_limit = min(requested_delegate, self.research.max_model_calls)
        # Hold input-summary capacity as well as an answer call for the parent.
        self.final_compaction = self.reserve_final_summary()
        self.recovery = CallAllowance(final, self.total)

    def reserve_final_summary(self):
        return FinalSummaryBudget(self.compaction, self.compaction.reserve())

    def attributes(self):
        values = {
            "total": self.total,
            "research": self.research,
            "compaction": self.compaction,
            "recovery": self.recovery,
        }
        return {
            "theos.budget.enforced": self.enforced,
            "theos.budget.delegate.limit": self.delegate_limit if self.enforced else -1,
            **{
                f"theos.budget.{name}.{field}": (
                    -1 if field == "limit" and not self.enforced else getattr(budget, source, 0)
                )
                for name, budget in values.items()
                for field, source in (
                    ("limit", "max_model_calls"),
                    ("used", "used"),
                    ("held", "held"),
                )
            },
        }

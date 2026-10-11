"""Separate call allowances under one turn ceiling."""

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


class TurnBudget:
    """Keep research, compaction, and recovery within the configured total."""

    def __init__(self, settings):
        self.total = Budget(settings.max_model_calls)
        final = 1
        # Small ceilings retain one research call before allocating compaction.
        compact = min(settings.max_compaction_calls, max(0, settings.max_model_calls - final - 1))
        self.research = CallAllowance(settings.max_model_calls - compact - final, self.total)
        self.compaction = CallAllowance(compact, self.total)
        self.recovery = CallAllowance(final, self.total)

    def attributes(self):
        values = {
            "total": self.total,
            "research": self.research,
            "compaction": self.compaction,
            "recovery": self.recovery,
        }
        return {
            f"theos.budget.{name}.{field}": getattr(budget, source)
            for name, budget in values.items()
            for field, source in (("limit", "max_model_calls"), ("used", "used"))
        }

import pytest

from harness import AssistantMessage, UserMessage
from harness.titles import conversation_title


@pytest.mark.parametrize(('messages', 'expected'), [
    (["Hello!", "Could you please plan my workouts for this week?"], "Plan my workouts for this week"),
    (["Please explain rest between sets. I have more questions."], "Explain rest between sets"),
    (["# Context from my IDE\nSome unrelated file names\n## My request:\nFix the session picker"],
     "Fix the session picker"),
    (["### Plan my week\n- Monday\n- Tuesday"], "Plan my week Monday Tuesday"),
    (["Hey"], "Greeting"),
    ([], "New conversation"),
])
def test_conversation_titles_use_the_request(messages, expected):
    history = [AssistantMessage(text="Unrelated response"), *map(UserMessage, messages)]
    assert conversation_title(history) == expected


def test_titles_end_at_word_boundaries():
    title = conversation_title([UserMessage("Please explain " + "recovery planning " * 30)])
    assert len(title) <= 64
    assert title.endswith("…")
    assert title.removesuffix("…").split()[-1] in {"recovery", "planning"}

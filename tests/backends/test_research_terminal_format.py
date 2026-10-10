from scitaste.backends.research_provider import terminal_proposal


def test_identical_terminal_submissions_do_not_require_invented_alternatives():
    item = {"tool": "Final Answer", "arguments": {"final_solution": "y=x"}, "rationale": "done"}
    assert terminal_proposal({"proposals": [item, {**item, "rationale": "same evidence"}]}) == item
    assert terminal_proposal({"proposals": [item]}) == item
    assert (
        terminal_proposal(
            {
                "proposals": [
                    item,
                    {
                        **item,
                        "arguments": {"final_solution": "y=2*x"},
                    },
                ]
            }
        )
        is None
    )
    assert terminal_proposal({"proposals": [{**item, "tool": "Run Experiments"}]}) is None

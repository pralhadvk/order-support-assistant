from assistant.synthesis import check_grounding

DOC2 = {"DOC-2": "the amount is auto-reversed within 24-48 hours under the payment gateway's standard TAT."}


def test_grounded_answer_passes():
    answer = "Your payment failed [ORDER]. The amount is auto-reversed within 24-48 hours [DOC-2]."
    assert check_grounding(answer, DOC2, []).ok


def test_citation_placed_at_end_of_paragraph_passes():
    answer = "It usually comes back on its own within 24-48 hours. No action is needed before then [DOC-2]."
    assert check_grounding(answer, DOC2, []).ok


def test_restating_the_customers_figures_passes():
    assert check_grounding("You mentioned it's been 9 days.", DOC2, ["it's been 9 days for order #4521"]).ok


def test_elapsed_time_from_order_record_passes():
    assert check_grounding("Your payment failed 5 days ago, on 22 Sep [ORDER].", DOC2, []).ok


def test_citation_of_unretrieved_doc_fails():
    result = check_grounding("Refunds take 5-7 business days [DOC-1].", DOC2, [])
    assert result.unknown_citations == {"DOC-1"}


def test_invented_timeline_fails_even_with_a_citation():
    result = check_grounding("You'll get your money in 3-5 business days [DOC-2].", DOC2, [])
    assert not result.ok and result.unsupported_claims


def test_answer_without_timelines_needs_no_citation():
    assert check_grounding("Could you share your order ID, e.g. ORD-1234?", {}, []).ok

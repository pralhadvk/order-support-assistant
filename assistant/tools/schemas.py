"""Tool definitions exposed to the LLM, in OpenAI function-calling format (what OpenRouter accepts).

customer_id is deliberately absent from every schema: it comes from the authenticated session,
so the model can never be talked into querying someone else's account.
"""

CHECK_ORDER_STATUS = {
    "type": "function",
    "function": {
        "name": "check_order_status",
        "description": "Returns the current status of a customer order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order reference ID, e.g. ORD-4521"},
            },
            "required": ["order_id"],
        },
    },
}

INITIATE_RETURN = {
    "type": "function",
    "function": {
        "name": "initiate_return",
        "description": "Initiates a return/refund workflow for an order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {"type": "string", "description": "Customer-stated reason for the return/refund request"},
            },
            "required": ["order_id", "reason"],
        },
    },
}

# Not in the brief's two schemas, but in the reference diagram and required by example query 3.
RAISE_DISPUTE = {
    "type": "function",
    "function": {
        "name": "raise_dispute",
        "description": (
            "Raises a platform dispute when a refund or payment auto-reversal has not arrived "
            "within its stated window."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {"type": "string", "description": "Customer-stated reason for the dispute"},
            },
            "required": ["order_id", "reason"],
        },
    },
}

COMMERCE_TOOLS = [CHECK_ORDER_STATUS, INITIATE_RETURN, RAISE_DISPUTE]

# The RAG path is exposed as a tool so the model can combine it with live order data in one turn
# ("both" queries) and decompose compound questions into focused searches.
SEARCH_POLICY = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": (
            "Searches the company's support policies and FAQs. The only permitted source for any policy, "
            "timeline or process statement. Use one focused query per topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A focused question about one policy topic"},
                "order_id": {
                    "type": "string",
                    "description": (
                        "Optional. An order already looked up with check_order_status; results are then "
                        "restricted to policies that apply to that order's actual status."
                    ),
                },
            },
            "required": ["query"],
        },
    },
}

ESCALATE_TO_HUMAN = {
    "type": "function",
    "function": {
        "name": "escalate_to_human",
        "description": "Hands the conversation to a human support agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why a human is needed"},
                "summary": {"type": "string", "description": "Short summary of the issue for the agent"},
            },
            "required": ["reason", "summary"],
        },
    },
}

ALL_TOOLS = [SEARCH_POLICY, *COMMERCE_TOOLS, ESCALATE_TO_HUMAN]

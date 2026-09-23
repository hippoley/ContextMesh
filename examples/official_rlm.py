"""Optional official RLM integration example.

Requires: pip install -e '.[rlm]'
Set provider credentials expected by the chosen RLM backend.
"""
from contextmesh.rlm_bridge import build_rlm_tool_bundle, create_official_rlm
from contextmesh.store import FileContextStore

store = FileContextStore(".contextmesh/store")
bundle = build_rlm_tool_bundle(store, "demo")

rlm = create_official_rlm(
    bundle,
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-nano"},
    max_iterations=40,
    max_depth=2,
    compaction=True,
)

result = rlm.completion(
    prompt=bundle.context_descriptor(
        question="Does the 30-day rule apply to old enterprise contracts?",
        answer="Yes, it applies to every purchase.",
    ),
    root_prompt=(
        "Evaluate the candidate answer. Use ContextMesh cm_* tools. "
        "Do not finish until cm_coverage() reports complete=true."
    ),
)
print(result.response)
print(bundle.session.coverage())

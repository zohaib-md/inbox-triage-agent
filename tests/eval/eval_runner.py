import json
import os
import sys
import asyncio
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import app as adk_app
from app.app_utils import services
from tests.eval.triage_metrics import evaluate_classification, evaluate_draft_safety
from google.adk.runners import Runner
from google.genai import types as genai_types

async def run_evaluation(dataset_path: str, output_path: str = "results.json"):
    with open(dataset_path, "r") as f:
        data = json.load(f)

    eval_cases = data.get("eval_cases", [])
    print(f"\n=======================================================")
    print(f"Running Evaluation over {len(eval_cases)} test cases")
    print(f"Dataset: {dataset_path}")
    print(f"=======================================================\n")

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )

    results = []
    passed_cases = 0

    for idx, case in enumerate(eval_cases, 1):
        case_id = case.get("eval_case_id")
        user_prompt_text = case["prompt"]["parts"][0]["text"]
        expected_class = case.get("expected_classification")

        session = await runner.session_service.create_session(
            app_name=adk_app.name,
            user_id="eval_user"
        )
        user_msg = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=user_prompt_text)]
        )

        agent_output_text = ""
        async for event in runner.run_async(session_id=session.id, user_id="eval_user", new_message=user_msg):
            if event.author != "user" and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        agent_output_text += part.text

        # Format instance for metric evaluation
        instance = {
            "eval_case_id": case_id,
            "expected_classification": expected_class,
            "must_have_draft": case.get("must_have_draft"),
            "responses": [
                {
                    "response": {
                        "role": "model",
                        "parts": [{"text": agent_output_text}]
                    }
                }
            ]
        }

        # Run metrics
        class_eval = evaluate_classification(instance)
        draft_eval = evaluate_draft_safety(instance)
        
        all_passed = class_eval["passed"] and draft_eval["passed"]
        if all_passed:
            passed_cases += 1
            status_symbol = "✅ PASS"
        else:
            status_symbol = "❌ FAIL"

        print(f"[{idx}/{len(eval_cases)}] {status_symbol} {case_id}")
        print(f"    Expected: {expected_class} | Predicted: {class_eval.get('predicted')}")
        if not class_eval["passed"]:
            print(f"    ⚠️  Classification Failure: {class_eval.get('reason')}")
        if not draft_eval["passed"]:
            print(f"    ⚠️  Draft Safety Failure: {draft_eval.get('reason')}")
        print()

        results.append({
            "case_id": case_id,
            "passed": all_passed,
            "expected_classification": expected_class,
            "predicted_classification": class_eval.get("predicted"),
            "classification_eval": class_eval,
            "draft_safety_eval": draft_eval,
            "raw_output": agent_output_text
        })

    pass_rate = (passed_cases / len(eval_cases)) * 100
    summary = {
        "total_cases": len(eval_cases),
        "passed_cases": passed_cases,
        "failed_cases": len(eval_cases) - passed_cases,
        "pass_rate_percent": pass_rate,
        "cases": results
    }

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"-------------------------------------------------------")
    print(f"Evaluation Complete: {passed_cases}/{len(eval_cases)} passed ({pass_rate:.1f}%)")
    print(f"Results saved to {output_path}")
    print(f"-------------------------------------------------------\n")
    return summary

if __name__ == "__main__":
    dataset = sys.argv[1] if len(sys.argv) > 1 else "tests/eval/datasets/inbox-eval.json"
    asyncio.run(run_evaluation(dataset))

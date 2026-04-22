import argparse
import json
import sys
import traceback
from llama_cpp import Llama


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--context-length", type=int, default=4096)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=512)
    return parser


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def run():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    llm = Llama(
        model_path=args.model_path,
        n_ctx=args.context_length,
        n_threads=args.threads,
        n_batch=args.batch_size,
        verbose=False,
    )
    emit({"ok": True, "type": "ready"})

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            message_type = request.get("type")

            if message_type == "shutdown":
                emit({"ok": True, "type": "shutdown"})
                return

            if message_type != "translate":
                emit({"ok": False, "type": "error", "error": "未知请求类型"})
                continue

            result = llm(
                request.get("prompt", ""),
                max_tokens=max(1, int(request.get("max_tokens", 768))),
                temperature=float(request.get("temperature", 0.3)),
                stop=["<|im_end|>", "<|im_start|>"],
                stream=True,
            )
            full_text = ""
            for chunk in result:
                token_text = chunk["choices"][0]["text"]
                if token_text:
                    full_text += token_text
                    emit({"type": "token", "text": token_text})
            emit({"ok": True, "type": "result", "text": full_text.strip()})
        except Exception as exc:
            emit(
                {
                    "ok": False,
                    "type": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )


if __name__ == "__main__":
    run()

{
  "app_url": "http://localhost:8092",
  "vllm_metrics_url": "http://localhost:8100/metrics",
  "corpus": {
    "corpus_version": "c2d8c188e9e6",
    "corpus_tokens": 7628,
    "tokenizer": "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
    "sources": [
      "routing-architecture.md",
      "gateway-integration.md",
      "operator-guide.md",
      "cost-model.md",
      "routing-behavior.md",
      "rag-design.md"
    ]
  },
  "config": {
    "n_warm": 10,
    "max_output_tokens": 1024,
    "counter_names": [
      "vllm:prefix_cache_queries_total",
      "vllm:prefix_cache_hits_total"
    ]
  },
  "readiness": {
    "waited_s": 0.358,
    "polls": 1
  },
  "prime": {
    "question": "Which model value forces the CPU tier, and which forces the GPU tier?",
    "ttft_s": 0.5334572909996496,
    "latency_s": 3.694526,
    "usage": {
      "prompt_tokens": 7802,
      "total_tokens": 7860,
      "completion_tokens": 58
    },
    "note": "first request after readiness: cache-priming prefill, not pod startup; pod startup time belongs to the readiness phase"
  },
  "warm": {
    "samples": [
      {
        "iteration": 1,
        "question": "How long does a GPU cold start take with a warm PVC and with a cold PVC?",
        "ttft_s": 0.686386917001073,
        "latency_s": 2.702967,
        "usage": {
          "prompt_tokens": 7805,
          "total_tokens": 7842,
          "completion_tokens": 37
        }
      },
      {
        "iteration": 2,
        "question": "What breaks when llama.cpp's timings field reaches the semantic router?",
        "ttft_s": 0.5095448749998468,
        "latency_s": 8.011831,
        "usage": {
          "prompt_tokens": 7800,
          "total_tokens": 7936,
          "completion_tokens": 136
        }
      },
      {
        "iteration": 3,
        "question": "How do the vLLM and llama.cpp backends authenticate client requests?",
        "ttft_s": 0.5289394999999786,
        "latency_s": 3.798352,
        "usage": {
          "prompt_tokens": 7802,
          "total_tokens": 7862,
          "completion_tokens": 60
        }
      },
      {
        "iteration": 4,
        "question": "How do you expose the gateway to local clients?",
        "ttft_s": 0.5355737080026302,
        "latency_s": 8.12488,
        "usage": {
          "prompt_tokens": 7797,
          "total_tokens": 7936,
          "completion_tokens": 139
        }
      },
      {
        "iteration": 5,
        "question": "What does a 400 invalid inference request mean and how do you fix it?",
        "ttft_s": 0.5088405829992553,
        "latency_s": 9.467261,
        "usage": {
          "prompt_tokens": 7805,
          "total_tokens": 7968,
          "completion_tokens": 163
        }
      },
      {
        "iteration": 6,
        "question": "What is the idle monthly cost of the stack?",
        "ttft_s": 0.5289362910007185,
        "latency_s": 2.545702,
        "usage": {
          "prompt_tokens": 7797,
          "total_tokens": 7834,
          "completion_tokens": 37
        }
      },
      {
        "iteration": 7,
        "question": "What is the minimum billed time to budget per GPU wake?",
        "ttft_s": 0.587764750001952,
        "latency_s": 2.313576,
        "usage": {
          "prompt_tokens": 7799,
          "total_tokens": 7831,
          "completion_tokens": 32
        }
      },
      {
        "iteration": 8,
        "question": "Why does the routing stack accept false positives?",
        "ttft_s": 0.5619840409999597,
        "latency_s": 5.502446,
        "usage": {
          "prompt_tokens": 7796,
          "total_tokens": 7887,
          "completion_tokens": 91
        }
      },
      {
        "iteration": 9,
        "question": "Which response headers and log events show the router's decision?",
        "ttft_s": 0.5469332079992455,
        "latency_s": 9.428012,
        "usage": {
          "prompt_tokens": 7799,
          "total_tokens": 7961,
          "completion_tokens": 162
        }
      },
      {
        "iteration": 10,
        "question": "Why was a dedicated rag-pool introduced?",
        "ttft_s": 0.5342849170010595,
        "latency_s": 5.206633,
        "usage": {
          "prompt_tokens": 7796,
          "total_tokens": 7881,
          "completion_tokens": 85
        }
      }
    ]
  },
  "cache_reuse_evidence": {
    "before": {
      "vllm:prefix_cache_queries_total": 85798.0,
      "vllm:prefix_cache_hits_total": 77760.0
    },
    "after": {
      "vllm:prefix_cache_queries_total": 171596.0,
      "vllm:prefix_cache_hits_total": 163472.0
    },
    "counter_deltas": {
      "vllm:prefix_cache_queries_total": 85798.0,
      "vllm:prefix_cache_hits_total": 85712.0
    },
    "verdict": "VERIFIED"
  },
  "restart_test": null
}
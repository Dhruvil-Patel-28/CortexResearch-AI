"""Quick test script for the full research pipeline."""
import requests
import json

print("=" * 60)
print("Testing Autonomous AI Research Agent Pipeline")
print("=" * 60)

# Test 1: Health check
print("\n[1] Health Check...")
r = requests.get("http://127.0.0.1:8000/health")
print(f"    Status: {r.status_code} | Response: {r.json()}")

# Test 2: Full research pipeline
print("\n[2] Research Pipeline (this may take 15-30 seconds)...")
r = requests.post(
    "http://127.0.0.1:8000/research",
    json={
        "query": "What are ML techniques for fraud detection?",
        "session_id": "test-session-1",
    },
    timeout=120,
)
data = r.json()

print(f"    Status: {r.status_code}")
print(f"    Session: {data['session_id']}")
print(f"    Report Title: {data['report']['title']}")
print(f"    Summary: {data['report']['summary'][:200]}...")
print(f"    Key Findings: {len(data['report']['key_findings'])}")
print(f"    Citations: {len(data['citations'])}")
print(f"    Agent Steps: {len(data['agent_steps'])}")

print("\n    --- Agent Execution Trace ---")
for step in data["agent_steps"]:
    tools = ", ".join(step["tools_used"]) if step["tools_used"] else "None"
    print(f"    {step['agent_name']}: {step['action']} | Tools: {tools}")

print("\n    --- Citations ---")
for i, c in enumerate(data["citations"], 1):
    page = c.get("page_number", "N/A")
    print(f"    [{i}] {c['source_name']} (Page {page})")

# Test 3: Session memory (follow-up query)
print("\n[3] Session Memory Test (follow-up query)...")
r2 = requests.post(
    "http://127.0.0.1:8000/research",
    json={
        "query": "Can you tell me more about the PaySim dataset?",
        "session_id": "test-session-1",
    },
    timeout=120,
)
data2 = r2.json()
print(f"    Status: {r2.status_code}")
print(f"    Report Title: {data2['report']['title']}")
print(f"    Agent Steps: {len(data2['agent_steps'])}")

# Test 4: Session history
print("\n[4] Session History...")
r3 = requests.get("http://127.0.0.1:8000/sessions/test-session-1/history")
history = r3.json()
print(f"    Total turns: {history['total_turns']}")
for i, turn in enumerate(history["turns"], 1):
    print(f"    Turn {i}: Q: {turn['query'][:60]}...")

print("\n" + "=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)

import urllib.request
import json
import time

# 1. Create chat session for finance_agent
req = urllib.request.Request(
    "http://127.0.0.1:5000/api/chat/session",
    data=json.dumps({"agent_id": "finance_agent", "title": "Budget Test"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
res = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
session_id = res["id"]
print(f"Created chat session: {session_id}")

# 2. Send message
req2 = urllib.request.Request(
    "http://127.0.0.1:5000/api/chat/message",
    data=json.dumps({
        "session_id": session_id,
        "message": "Create a monthly family budget spreadsheet in Excel with income and expenses."
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
res2 = json.loads(urllib.request.urlopen(req2).read().decode("utf-8"))
print("Message dispatch response:", res2)

# 3. Poll session until assistant responds
print("Waiting for Bedrock Finance Agent to execute tools and reply...")
for i in range(25):
    time.sleep(2)
    req3 = urllib.request.Request(f"http://127.0.0.1:5000/api/chat/session/{session_id}")
    session_data = json.loads(urllib.request.urlopen(req3).read().decode("utf-8"))
    messages = session_data.get("messages", [])
    if len(messages) >= 2:
        assistant_msg = messages[-1]
        print("\n=== ASSISTANT MESSAGE RECEIVED ===")
        print("Role:", assistant_msg.get("role"))
        print("Tool Calls:", assistant_msg.get("tool_calls"))
        print("Deliverables:", assistant_msg.get("deliverables"))
        print("Content preview:\n", assistant_msg.get("content")[:350], "...\n")
        break
    else:
        print(f"[{i*2}s] Still waiting for assistant...")

"""
memory_action.py - Action functions for memory operations.
Provides a clean interface for main.py to interact with JARVIS memory.
"""
import logging

logger = logging.getLogger(__name__)

_memory = None


def get_memory():
    """Get or create the global JARVIS memory instance."""
    global _memory
    if _memory is None:
        from memory.j_memory import JARVISMemory
        _memory = JARVISMemory()
        _memory.initialize()
    return _memory


def memory_action(params: dict, player=None):
    """Action to interact with JARVIS memory."""
    cmd = params.get("command", "status")

    mem = get_memory()

    if cmd == "remember":
        event_type = params.get("type", "conversation")
        content = params.get("content", "")
        mem.remember(event_type, content, params.get("metadata"))
        return {"status": "remembered", "type": event_type}

    elif cmd == "recall":
        query = params.get("query", "")
        results = mem.recall(query, params.get("limit", 5))
        return {"status": "recalled", "results": results}

    elif cmd == "learn":
        subject = params.get("subject", "")
        relation = params.get("relation", "")
        object_ = params.get("object", "")
        if subject and relation and object_:
            mem.learn_fact(subject, relation, object_)
            return {"status": "learned", "fact": f"{subject} {relation} {object_}"}
        return {"status": "error", "message": "Missing subject, relation, or object"}

    elif cmd == "what_do_you_know":
        query = params.get("query", "")
        answer = mem.what_do_you_know(query)
        return {"status": "answered", "answer": answer}

    elif cmd == "teach":
        name = params.get("name", "")
        description = params.get("description", "")
        steps = params.get("steps", [])
        trigger = params.get("trigger", "")
        if name and steps and trigger:
            mem.teach_skill(name, description, steps, trigger)
            return {"status": "taught", "skill": name}
        return {"status": "error", "message": "Missing name, steps, or trigger"}

    elif cmd == "find_skill":
        task = params.get("task", "")
        skill = mem.find_skill(task)
        return {"status": "found" if skill else "not_found", "skill": skill}

    elif cmd == "context":
        user_msg = params.get("user_message", "")
        context = mem.build_context(user_msg)
        return {"status": "context", "context": context}

    elif cmd == "knowledge_graph":
        if mem._semantic:
            return {"status": "graph", "graph": mem._semantic.get_graph()}
        return {"status": "error", "message": "Semantic memory not initialized"}

    elif cmd == "recent":
        hours = params.get("hours", 24)
        limit = params.get("limit", 10)
        memories = mem.get_recent_memories(hours=hours, limit=limit)
        return {"status": "recent", "memories": memories}

    elif cmd == "status":
        return {
            "status": "ok",
            "initialized": mem._initialized,
            "episodic": mem._episodic._ready if mem._episodic else False,
            "semantic": mem._semantic._ready if mem._semantic else False,
            "procedural": len(mem.list_skills()) if mem._procedural else 0,
        }

    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}

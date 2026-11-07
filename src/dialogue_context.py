"""Bounded conversation context with explicit references, not just prose tails."""
import re


def recent_context(messages):
    result = []
    for message in messages[-6:]:
        if message.get('role') not in {'user', 'assistant'}:
            continue
        audit = (message.get('response') or {}).get('answer_audit') or {}
        citations = audit.get('citations', [])
        ids = list(dict.fromkeys(c['paper_id'] for c in citations if isinstance(c, dict) and c.get('paper_id')))
        result.append({'role': message['role'], 'content': str(message.get('content', ''))[:6000],
                       'paper_ids': audit.get('scope_paper_ids') or ids})
    return result


def referenced_papers(question, history, allowed):
    if not re.search(r'这两篇|这两种|这些方案|这两个|前一篇|后一篇|第二篇|第一篇|刚才比较', question):
        return []
    for message in reversed(history):
        if message.get('role') != 'assistant':
            continue
        ids = [pid for pid in message.get('paper_ids', []) if pid in allowed]
        if ids:
            if re.search(r'后一篇|第二篇', question):
                return ids[1:2]
            if re.search(r'前一篇|第一篇', question):
                return ids[:1]
            return ids
    return []

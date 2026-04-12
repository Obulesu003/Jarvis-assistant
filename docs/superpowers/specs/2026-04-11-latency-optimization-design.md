# Latency Optimization Design — Mark-XXXV

**Date:** 2026-04-11
**Status:** Implemented

## Problem

LLMOrchestrator makes **2 separate Gemini API calls** per request:
1. `_plan_steps_llm()` — classifies intent, plans steps
2. `_format_response_llm()` — formats results into natural language

This doubles network latency for every assistant tool call.

## Solution: Combined Single-Call Approach

Merge planning + response into one API call via `execute_combined()`.
The LLM returns both the execution plan AND a response template with placeholders.
After executing steps, placeholders are substituted with actual results.

### Before (2 API calls)
```
execute() → _plan_steps_llm() [API call 1]
          → _execute_steps()
          → _format_response_llm() [API call 2]
```

### After (1 API call)
```
execute() → execute_combined() [API call 1]
          → _execute_steps()
          → _fill_response_template() [no API call]
```

## Implementation

### New method: `execute_combined()`
- Builds a combined prompt asking the LLM to return:
  - `"steps"`: execution plan (same format as before)
  - `"response_template"`: natural language with `${{results.0}}` placeholders
- Parses the combined JSON response
- Executes steps
- Substitutes placeholders with actual results
- Falls back to two-call approach if parsing fails or API errors

### New method: `_parse_combined_response()`
- Extracts JSON from markdown code blocks
- Returns parsed dict or None

### New method: `_fill_response_template()`
- Substitutes `${{results.N}}` with human-readable summaries
- Uses existing `_summarize_result()` for smart formatting

### New method: `_fallback_via_two_call()`
- Original two-call approach as fallback
- Handles rate limit errors gracefully

### New prompt: `COMBINED_PROMPT`
- Asks LLM to plan AND format in one pass
- Uses placeholder syntax: `${{results.0}}`, `${{results.1}}`, etc.

## Fallback Chain

```
execute()
  └─ execute_combined() [primary]
       ├─ Success → fill template → return
       ├─ Parse failure → _fallback_via_two_call()
       └─ API error → _fallback_via_two_call()
            ├─ _plan_steps_llm() [fallback 1]
            ├─ _plan_steps_keyword() [fallback 2]
            └─ _fallback_response() [final]
```

## Performance Impact

| Metric | Before | After | Improvement |
|--------|-------|-------|-------------|
| API calls per request | 2 | 1 | **50% reduction** |
| Network latency | ~1-2s × 2 | ~1-2s × 1 | **~50% faster** |

## Testing

- `tests/test_llm_orchestrator.py` covers:
  - Combined response parsing
  - Placeholder substitution
  - Fallback chain on parse failure
  - Fallback chain on API error

## Files Modified

- `integrations/core/llm_orchestrator.py` — new methods + COMBINED_PROMPT
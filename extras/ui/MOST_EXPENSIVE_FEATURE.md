# Most Expensive Message Feature

Quick way to find and jump to the most expensive LLM call in a session.

## Features

### Backend (`message_flow_api.py`)
- Analyzes all messages in a session
- Finds the message with highest cost
- Returns metadata in `cost_summary.most_expensive`:
  ```json
  {
    "index": 42,
    "cost": 0.0234,
    "tokens_in": 12543,
    "role": "assistant",
    "node_type": "follow_up",
    "phase_name": "generate",
    "sounding_index": null,
    "reforge_step": null,
    "turn_number": 3
  }
  ```

### Frontend (`MessageFlowView.js`)
1. **Cost Summary Button**
   - Shows most expensive cost and token count
   - Click to scroll to the message
   - Orange gradient styling

2. **Message Highlighting**
   - Most expensive message has permanent orange border + glow
   - Pulsing gold badge: "💰 Most Expensive"
   - Temporary flash animation when scrolled to (3 seconds)

3. **Smooth Scroll**
   - Automatically centers the message in viewport
   - Highlights with animation to draw attention

## Visual Design

**Most Expensive Button (in cost summary):**
- Orange background with gradient hover
- Format: `💰 Most Expensive: $0.0234 (12,543 tokens)`
- Right-aligned in cost summary section

**Most Expensive Badge (on message):**
- Gold gradient badge with pulsing glow animation
- Always visible on the most expensive message
- Format: `💰 Most Expensive`

**Message Styling:**
- Orange border (#fb923c)
- Subtle orange glow (box-shadow)
- Highlighted state with flash animation

## Usage

1. Load a session in MessageFlowView
2. Look at the cost summary - button appears if there's cost data
3. Click "💰 Most Expensive" button
4. Page smoothly scrolls to the message
5. Message flashes gold for 3 seconds to draw attention

## Use Case

Perfect for debugging high-cost cascades:
- Quickly identify the single most expensive LLM call
- See which phase/turn generated the cost
- Check if it's in a sounding, reforge, or main flow
- Examine the full request to understand token usage

## Cost Analysis Workflow

1. Notice high session cost in dashboard
2. Open MessageFlowView for that session
3. Click "Most Expensive" button
4. Examine that specific message:
   - Expand to see full request
   - Count images if present
   - Check for large error messages
   - Review prompt engineering

This makes cost debugging instant instead of scrolling through hundreds of messages!

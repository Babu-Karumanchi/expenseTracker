# Spec: AI Expense Insights

## Overview
The AI Expense Insights feature provides users with natural-language analysis of their spending habits. By analyzing recent transaction history and budget adherence, the system generates personalized observations and actionable advice to help users optimize their finances.

## Depends on
- Step 05: Backend routes for profile page
- Step 10: Analytics page

## Routes
- `GET /insights` — Generate and display AI-driven spending insights — logged-in

## Database changes
No database changes.

## Templates
- **Create:** `templates/insights.html`

## Files to change
- `app.py`

## Files to create
- `templates/insights.html`

## New dependencies
No new dependencies. Implementation must use `urllib.request` from the Python standard library to perform API calls.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **AI Integration:**
    - Fetch expense data for the last 3 months to build the analysis context.
    - Use `urllib.request` to send a prompt to an LLM API (e.g., OpenAI or Anthropic).
    - The API key must be retrieved from `os.environ.get("SPENDLY_AI_KEY")`.
    - Implement a fallback: if the API key is missing or the request fails, render a helpful message stating that AI insights are temporarily unavailable, rather than returning an error page.
    - Ensure the prompt explicitly requests a concise, friendly tone suitable for an Indian audience (referencing INR/₹).

## Definition of done
- [ ] Navigating to `/insights` while logged in renders the `insights.html` page.
- [ ] The page displays AI-generated insights based on the current user's real expense data.
- [ ] If `GROQ_API_KEY` is unset, the page renders a graceful fallback message.
- [ ] The insights are presented in a clean, readable format that matches the Spendly branding.
- [ ] Route is protected; signed-out users are redirected to `/login`.

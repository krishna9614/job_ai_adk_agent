# job_ai_adk_agent

JobAI v1.0 backend: a FastAPI API (signup, login, user profile) plus the single Google ADK
agent. It owns the profile business logic and all SQL; the User Profile MCP server
([job_ai_user_profile_mcp](https://github.com/krishna9614/job_ai_user_profile_mcp)) calls
this API on behalf of the authenticated user.

```text
app/api/v1/        FastAPI routes (auth, users, agent)        HTTP + validation
app/api/deps.py    DI: DB session, auth provider, current user
app/services/      auth, user sync, profile, agent runner     business logic
app/services/auth_provider.py   Supabase Auth adapter (AuthProvider interface)
app/repositories/  users / user_profiles queries              data access
app/models/        SQLAlchemy 2 models mapped to jobai.users, jobai.user_profiles
job_ai_agent/      ADK root agent (Gemini) + Profile MCP toolset
db/jobai_v1_schema.sql   authoritative schema (reference; app never runs DDL)
tests/             pytest (Supabase mocked, real test database)
```

## How auth works

- Supabase Auth stores the credentials and issues the tokens. Passwords never reach our tables.
- `POST /auth/signup` and `POST /auth/login` call Supabase with the **anon/publishable key**.
  On success, the Supabase user is upserted into `jobai.users` by `auth_user_id`. Repeating
  this is safe.
- Protected routes need `Authorization: Bearer <supabase access_token>`. The token is checked
  with Supabase (JWKS signature check for asymmetric keys, or an Auth server call for legacy
  HS256 keys), and the current user comes from its `sub` claim. No endpoint accepts a `user_id`.
- Duplicate email returns `409`. A bad password returns `401`. An unconfirmed email returns `403`.
  A suspended or deleted account returns `403`. If Supabase is not configured, the API returns `503`.

### Supabase setup

1. Create a Supabase project. In **Authentication → Sign In / Providers**, enable **Email**.
2. In **Project Settings → API Keys**, copy the project URL and the **publishable (anon)** key
   into `SUPABASE_URL` and `SUPABASE_ANON_KEY`. Do **not** use the service-role/secret key.
3. Email confirmation:
   - **On** (Supabase default): signup returns `201` with `session: null` and
     `email_confirmation_required: true`. Login works after the user clicks the email link.
   - **Off**: signup returns a session straight away. Use this for local development.

## Local setup

Requires Python 3.13 and PostgreSQL 18, with `jobai_db` already created from `db/jobai_v1_schema.sql`.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the values

# One-time: create the dedicated test database (pytest applies the schema to it)
psql -h localhost -U postgres -c "CREATE DATABASE jobai_test_db;"
```

## Run

Start three processes, each in its own terminal:

```bash
# 1. User Profile MCP server (in the job_ai_user_profile_mcp repo)
python server.py                       # http://127.0.0.1:8001/mcp

# 2. JobAI API + agent (this repo)
python -m app.main                     # http://127.0.0.1:8000  (docs: /docs)
```

```bash
# 3. Tests (this repo)
pytest
```

The Job Intelligence MCP server is not used in this phase.

## Agent

`job_ai_agent/agent.py` defines one `LlmAgent` with an `McpToolset` that connects to the
Profile MCP server.

- Only `get_user_profile` is exposed to the model (`tool_filter`). Creating or updating a
  profile stays an explicit user action through the REST API. Signup and login are never tools.
- `POST /api/v1/agent/chat` runs the agent for the authenticated caller. The caller's access
  token goes into `temp:` session state, which is never persisted. The toolset's
  `header_provider` forwards it to the MCP server, so the agent can only read the caller's
  own profile.

## API examples

Requests below use these variables:

```bash
API=http://127.0.0.1:8000/api/v1
TOKEN=<session.access_token from signup/login>
```

**Signup**: `201 Created`

```bash
curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"S3cure-pass!"}'
```

```json
{
  "user": {
    "id": "8eb95ecd-84de-4505-a568-c1a16d64c6fb",
    "email": "ada@example.com",
    "account_status": "active",
    "onboarding_status": "not_started",
    "onboarding_step": 0,
    "email_verified_at": "2026-10-31T22:17:19.456281Z",
    "last_login_at": "2026-10-31T22:17:19.461447Z",
    "created_at": "2026-10-31T22:17:19.454755Z",
    "updated_at": "2026-10-31T22:17:19.454755Z"
  },
  "session": {"access_token": "eyJ...", "refresh_token": "...", "token_type": "bearer", "expires_in": 3600},
  "email_confirmation_required": false
}
```

Signing up again with the same email returns `409 {"detail":"An account with this email already exists","code":"conflict"}`.

**Login**: `200 OK` (wrong credentials return `401 {"detail":"Invalid email or password","code":"not_authenticated"}`)

```bash
curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"S3cure-pass!"}'
```

The response has the same `user` + `session` shape as signup.

**Current user**: `200 OK` returns the `user` object. With no token or a bad one: `401`.

```bash
curl -s $API/users/me -H "Authorization: Bearer $TOKEN"
```

**Create profile**: `201 Created` (`first_name` is required; a second create returns `409`)

```bash
curl -s -X POST $API/users/me/profile -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Ada","last_name":"Lovelace","country_code":"gb","linkedin_url":"https://www.linkedin.com/in/ada"}'
```

```json
{
  "user_id": "8eb95ecd-84de-4505-a568-c1a16d64c6fb",
  "first_name": "Ada", "middle_name": null, "last_name": "Lovelace", "preferred_name": null,
  "phone_country_code": null, "phone_number": null,
  "city": null, "state_province": null, "country_code": "GB",
  "professional_headline": null, "professional_summary": null,
  "linkedin_url": "https://www.linkedin.com/in/ada", "github_url": null,
  "created_at": "2026-10-31T22:17:19.49Z", "updated_at": "2026-10-31T22:17:19.49Z"
}
```

**Get profile**: `200 OK` with the same shape. Returns `404` if no profile exists yet.

```bash
curl -s $API/users/me/profile -H "Authorization: Bearer $TOKEN"
```

**Update profile**: `200 OK`. Only the fields you send change, and `null` clears an optional field.

```bash
curl -s -X PATCH $API/users/me/profile -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"professional_headline":"Mathematician","city":null}'
```

**Agent chat**: `200 OK` (needs `GOOGLE_API_KEY` and the MCP server running)

```bash
curl -s -X POST $API/agent/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message":"What name is on my profile?"}'
# {"session_id":"...","reply":"Your profile lists you as Ada Lovelace."}
```

To continue a conversation, send the returned `session_id` with the next message.

# Implementation Plan: Ubuntu Connect

## Overview

This plan converts the Ubuntu Connect design into a sequence of incremental coding tasks. Work proceeds bottom-up: project scaffolding and fail-fast config first, then data models and repositories, then services (auth/OTP, profile, trust, AI, messaging, reporting, admin), then the Africa's Talking SMS/USSD integrations, then the Next.js design system, shared hooks, and pages, and finally end-to-end wiring plus smoke/architecture tests.

The backend is FastAPI + Pydantic v2 + SQLAlchemy 2.x on PostgreSQL; the frontend is Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui. Property-based tests use **Hypothesis** on the backend and **fast-check** on the frontend. Each of the 59 design correctness properties is implemented by exactly one property test, tagged `Feature: ubuntu-connect, Property {number}: {property_text}`, running a minimum of 100 generated examples. The OpenAI client is mocked in property tests so orchestration, thresholds, and fallbacks are exercised rather than the provider.

Test fixtures use realistic African data: Amara Okafor (+2348031234567), Thandiwe Nkosi (+27821234567), Kwame Mensah (+233201234567), Zainab Abdullahi (+254712345678), with interests such as Afrobeats production, isiZulu poetry, fintech meetups, and Swahili literature.

## Tasks

- [ ] 1. Scaffold backend project and fail-fast configuration
  - [x] 1.1 Create backend project structure and tooling
    - Create the `backend/app/` package tree (`routers/`, `services/`, `repositories/`, `ai/` with `fallback/` and `prompts/`, `integrations/`, `models/`, `schemas/`) with `__init__.py` files
    - Add `pyproject.toml`/`requirements.txt` pinning FastAPI, Pydantic v2, SQLAlchemy 2.x, psycopg, python-jose (JWT), pytest, and Hypothesis
    - Create `backend/app/main.py` app factory and a `pytest.ini`/`conftest.py` with a Hypothesis profile of min 100 examples
    - _Requirements: 15.1_

  - [-] 1.2 Implement environment-variable config with fail-fast validation
    - Create `backend/app/config.py` reading `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `AT_API_KEY`, `AT_USERNAME`, `AT_SMS_SENDER_ID`, `AT_USSD_SERVICE_CODE`, `PHOTO_STORAGE_BUCKET` from the environment with no literal credential/endpoint values in source
    - Implement `config.validate()` that collects every missing required variable and raises during app construction (before binding a port), emitting an error naming each missing variable
    - Wire `config.validate()` into the `main.py` app factory startup path
    - _Requirements: 15.4, 15.5_

  - [~] 1.3 Write property test for fail-fast env validation
    - **Feature: ubuntu-connect, Property 52: For any subset of required environment variables that is absent at startup, the backend halts without serving requests and emits an error naming each missing variable.**
    - **Validates: Requirements 15.5**

- [ ] 2. Implement data models and repository layer
  - [-] 2.1 Define SQLAlchemy ORM models and DB session wiring
    - Create `models/` entities: `User` (id, full_name, phone unique, bio, interests JSONB, profile_photo, trust_score, verified_phone, is_admin, created_at), `Message` (sender_id, receiver_id, content, moderation_result, scam_score nullable, delivered, created_at), `Report` (reporter, reported_user, reason, status, created_at), `TrustReason` (user_id, factor, contribution, description, created_at), `OtpCode` (user_id, code, failed_attempts, expires_at, invalidated, created_at)
    - Add `NotificationFailure` model (phone, notification_type, created_at) for Req 14.4
    - Create DB engine/session factory and a transactional session dependency used by routers
    - _Requirements: 1.1, 6.1, 12.1, 5.6, 2.2, 14.4_

  - [~] 2.2 Implement repository classes over the models
    - Create `repositories/base.py` and `user_repository.py`, `message_repository.py`, `report_repository.py`, `otp_repository.py`, `trust_reason_repository.py` holding all SQLAlchemy queries (create/read/update, ordering helpers, existence checks, count helpers)
    - Expose repositories via FastAPI dependency injection so services never touch sessions directly
    - _Requirements: 15.1_

  - [~] 2.3 Write unit tests for repositories against a test database
    - Test create/read round-trips, unique-phone enforcement, ascending/descending ordering helpers, and count helpers used by the Trust Engine and admin views
    - _Requirements: 15.1, 6.3_

- [ ] 3. Implement Pydantic schemas and global error envelope
  - [~] 3.1 Define request/response schemas and shared error envelope
    - Create `schemas/` Pydantic models for register, verify-otp, resend-otp, login, profile bio/interests/photo, message send, trust, report, and admin resolution requests/responses with field constraints (full_name 2–100, E.164 phone, bio ≤500, interests ≤20 items each ≤50, content 1–2000, reason 1–1000)
    - Implement the shared error envelope `{error:{code,message,fields[]}}` and a global exception handler mapping validation/auth/authorization/not_found/conflict/policy_violation/rate_limited/timeout/internal_error, ensuring generic messages and no leaked internals
    - Ensure write-path router dependency wraps handlers in a transaction that rolls back on exception (no partial writes)
    - _Requirements: 16.1, 16.2, 15.6_

  - [~] 3.2 Write property test for validation rejection with per-field reasons
    - **Feature: ubuntu-connect, Property 53: For any request with input that fails validation, the request is rejected, no changes are written to the data store, and the error response identifies each invalid field together with the reason it failed.**
    - **Validates: Requirements 16.1**

  - [~] 3.3 Write property test for safe unhandled-exception responses
    - **Feature: ubuntu-connect, Property 54: For any backend operation that raises an unhandled exception, the response carries a generic message with no internal details and previously persisted data is left unchanged.**
    - **Validates: Requirements 16.2**

- [ ] 4. Implement authentication and JWT issuance
  - [~] 4.1 Implement AuthService registration and login
    - Create `services/auth_service.py` registering users (verified_phone false, trust_score 0, created_at set) with duplicate-phone rejection and validation, and login issuing a JWT (24h expiry) only for verified accounts
    - Create `routers/auth.py` with `/api/auth/register` and `/api/auth/login` declaring explicit `response_model`
    - Implement the JWT auth-guard dependency rejecting missing/expired/invalid tokens, plus an admin role guard
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 11.1_

  - [~] 4.2 Write property test for registration defaults
    - **Feature: ubuntu-connect, Property 1: For any valid full name (2–100 characters) and any E.164 phone not already registered, registering creates exactly one user record with verified_phone false, trust_score 0, and created_at set.**
    - **Validates: Requirements 1.1, 1.6**

  - [~] 4.3 Write property test for duplicate-phone rejection
    - **Feature: ubuntu-connect, Property 2: For any phone already belonging to a user, a subsequent registration with that phone is rejected and the total user count is unchanged.**
    - **Validates: Requirements 1.2**

  - [~] 4.4 Write property test for registration input validation
    - **Feature: ubuntu-connect, Property 3: For any registration request, it is rejected identifying the offending field(s) when the phone is not valid E.164, when the phone or full name is missing, when the full name is empty/whitespace, or when the full name length is <2 or >100; otherwise it is accepted.**
    - Generators use E.164 African prefixes (+234, +27, +233, +254) and near-miss non-E.164 strings
    - **Validates: Requirements 1.3, 1.4, 1.5**

  - [~] 4.5 Write property test for login gating
    - **Feature: ubuntu-connect, Property 10: For any account, login issues a JWT identifying that user only when credentials are valid and verified_phone is true; it is rejected with a verification-required error when unverified, and with an authentication error when credentials match no record.**
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [~] 4.6 Write property test for login credential validation
    - **Feature: ubuntu-connect, Property 11: For any login request omitting a required credential field, the request is rejected identifying each missing field.**
    - **Validates: Requirements 3.4**

  - [~] 4.7 Write property test for JWT 24-hour expiry
    - **Feature: ubuntu-connect, Property 12: For any issued JWT, its expiry timestamp equals its issue timestamp plus 24 hours.**
    - **Validates: Requirements 3.5**

  - [~] 4.8 Write property test for protected-endpoint token rejection
    - **Feature: ubuntu-connect, Property 13: For any protected endpoint request carrying no token, an expired token, or an invalid/tampered token, the request is rejected with an authentication error.**
    - **Validates: Requirements 3.6**

- [ ] 5. Implement OTP service (depends on SMS gateway interface from task 12)
  - [~] 5.1 Implement OTPService generation, verification, and throttling
    - Create `services/otp_service.py` generating a 6-digit code with `expires_at = now + 10min`, requesting SMS delivery, verifying match+expiry+attempt-count order, invalidating on 5th failed attempt, and enforcing the 5-requests-per-60-minute resend cap (invalidate prior OTP, reset failures on valid resend)
    - Create `routers/auth.py` endpoints `/api/auth/verify-otp` and `/api/auth/resend-otp`; on OTP creation trigger the Trust Engine recalculation hook after verification
    - Handle SMS send failure by returning a send-failure error while keeping resend available
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [~] 5.2 Write property test for OTP generation shape and expiry
    - **Feature: ubuntu-connect, Property 4: For any newly created user, the generated OTP is a 6-digit numeric code, an SMS send is requested to that user's phone, and the stored OTP expiry equals its creation time plus 10 minutes.**
    - **Validates: Requirements 2.1, 2.2**

  - [~] 5.3 Write property test for correct-OTP verification
    - **Feature: ubuntu-connect, Property 5: For any stored OTP, submitting the matching code before its expiry sets the user's verified_phone to true.**
    - **Validates: Requirements 2.3**

  - [~] 5.4 Write property test for wrong-attempt accumulation and cap
    - **Feature: ubuntu-connect, Property 6: For any stored OTP, each wrong submission while fewer than 5 failures are recorded is rejected as incorrect and increments the failure count; the 5th wrong submission invalidates the OTP and returns a maximum-attempts error.**
    - **Validates: Requirements 2.4, 2.5**

  - [~] 5.5 Write property test for expired-OTP rejection
    - **Feature: ubuntu-connect, Property 7: For any stored OTP submitted at or after its expiry time, the submission is rejected as expired.**
    - **Validates: Requirements 2.6**

  - [~] 5.6 Write property test for OTP resend throttling
    - **Feature: ubuntu-connect, Property 8: For any user with fewer than 5 OTP requests in the trailing 60 minutes, a resend invalidates the prior OTP, resets the failed-attempt count, and generates a new OTP; the 6th request within the window is rejected with the resend-limit error.**
    - **Validates: Requirements 2.7, 2.8**

  - [~] 5.7 Write property test for recoverable SMS delivery failure
    - **Feature: ubuntu-connect, Property 9: For any OTP send that the SMS gateway reports as failed, the service returns a send-failure error and a subsequent resend is still permitted.**
    - **Validates: Requirements 2.9**

- [ ] 6. Implement profile service
  - [~] 6.1 Implement ProfileService and routes
    - Create `services/profile_service.py` validating and persisting bio (≤500), interests (≤20 items each ≤50, leaving existing unchanged on rejection), and photo (JPEG/PNG, ≤5 MB, storing URL/key), and returning profiles including Trust_Score and Verified_Phone
    - Create `routers/profiles.py` with `PUT /api/profile/bio`, `PUT /api/profile/interests`, `POST /api/profile/photo`, `GET /api/profile/{id}`; trigger Trust Engine recalculation on profile updates
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 9.4_

  - [~] 6.2 Write property test for bio round-trip and validation
    - **Feature: ubuntu-connect, Property 14: For any bio of 500 characters or fewer, saving then reading it returns the same value; for any bio longer than 500 characters, the update is rejected identifying the bio field.**
    - **Validates: Requirements 4.1, 4.2**

  - [~] 6.3 Write property test for interests round-trip and preservation
    - **Feature: ubuntu-connect, Property 15: For any interests list of at most 20 items each at most 50 characters, saving then reading returns the same list; for any list exceeding those limits, the update is rejected identifying the interests field and the previously stored interests are unchanged.**
    - **Validates: Requirements 4.3, 4.4**

  - [~] 6.4 Write property test for photo format and size validation
    - **Feature: ubuntu-connect, Property 16: For any uploaded photo, it is stored and associated with the user when it is JPEG or PNG and at most 5 MB; it is rejected identifying accepted formats for other formats, and rejected identifying the size limit when larger than 5 MB.**
    - **Validates: Requirements 4.5, 4.6, 4.7**

  - [~] 6.5 Write property test for profile display contents
    - **Feature: ubuntu-connect, Property 17: For any user, the displayed profile payload includes that user's current Trust_Score and Verified_Phone state.**
    - **Validates: Requirements 4.8, 9.4**

- [ ] 7. Implement the Trust Engine
  - [~] 7.1 Implement deterministic Trust Engine and endpoints
    - Create `services/trust_engine.py` computing `clamp(30*verified + 10*populated_fields + min(messages_sent,40) - 15*confirmed_reports, 0, 100)` and writing one `trust_reasons` row per factor on each recalculation
    - Create `routers/trust.py` with `GET /api/trust/{userId}` and `GET /api/trust/{userId}/explanation`, returning recorded reasons or an error when none exist
    - Expose a recalculation entry point invoked on phone verification, profile update, confirmed report, and message activity
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [~] 7.2 Write property test for bounded integer score
    - **Feature: ubuntu-connect, Property 18: For any user state, the computed Trust_Score is an integer in the inclusive range [0, 100].**
    - **Validates: Requirements 5.1**

  - [~] 7.3 Write property test for factor monotonicity
    - **Feature: ubuntu-connect, Property 19: For any two user states differing only in one factor, the Trust_Score is non-decreasing as phone verification becomes true, non-decreasing as more of the three profile fields are populated, and non-increasing as the count of confirmed reports increases.**
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [~] 7.4 Write property test for four-factor function equality
    - **Feature: ubuntu-connect, Property 20: For any user state, the Trust_Score equals the documented clamped function of exactly the four factors (phone verification, populated profile-field count, confirmed-report count, messages sent); changing an input outside those four does not change the score.**
    - **Validates: Requirements 5.5**

  - [~] 7.5 Write property test for complete reasons and explanation round-trip
    - **Feature: ubuntu-connect, Property 21: For any Trust_Score recalculation, the engine records one reason entry per contributing factor, and requesting the explanation returns exactly the recorded reason entries.**
    - **Validates: Requirements 5.6, 5.7**

  - [~] 7.6 Write unit test for explanation with no recorded entries
    - Assert `GET /api/trust/{userId}/explanation` returns a no-explanation-available error when no reasons exist
    - _Requirements: 5.8_

- [ ] 8. Implement AI moderation and scam detection with rule-based fallbacks
  - [~] 8.1 Implement OpenAI client and prompt modules
    - Create `integrations/openai_client.py` wrapping calls with explicit timeouts (5s moderation, 3s scam) and raising on timeout/error
    - Create `ai/prompts/moderation_prompt.py` and `ai/prompts/scam_prompt.py` that build prompts only, with no calling logic
    - _Requirements: 15.3, 7.6, 8.2_

  - [~] 8.2 Implement rule-based fallbacks
    - Create `ai/fallback/moderation_rules.py` mapping harmful keyword patterns to `blocked`/`flagged`/`approved`, and `ai/fallback/scam_rules.py` scoring money/urgency/prize-airtime/link signals clamped to [0,100]
    - _Requirements: 7.5, 8.2_

  - [~] 8.3 Implement ModerationService and ScamDetector
    - Create `ai/moderation_service.py` returning a label via OpenAI within budget and falling back to rules on timeout/error, and `ai/scam_detector.py` returning a [0,100] score with the same fallback behavior; both return the same typed result regardless of path
    - _Requirements: 7.1, 7.5, 7.6, 8.1, 8.2, 8.6_

  - [~] 8.4 Write property test for valid moderation label including fallback
    - **Feature: ubuntu-connect, Property 26: For any message — including when the OpenAI API is unavailable — moderation assigns a Moderation_Result that is one of "approved", "flagged", or "blocked".**
    - Mock the OpenAI client to simulate success, timeout, and error paths
    - **Validates: Requirements 7.1, 7.5**

  - [~] 8.5 Write property test for bounded scam score including fallback
    - **Feature: ubuntu-connect, Property 30: For any message that passes moderation — including when OpenAI errors or exceeds its time budget — the assigned Scam_Score is an integer in [0, 100] and is stored on the message before delivery.**
    - **Validates: Requirements 8.1, 8.2, 8.6**

  - [~] 8.6 Write unit tests for AI timeout switchover to fallback
    - Simulate OpenAI exceeding the 5s moderation and 3s scam budgets and assert the rule-based fallback result is used
    - _Requirements: 7.6, 8.2_

- [ ] 9. Implement the messaging pipeline and SSE delivery
  - [~] 9.1 Implement MessagingService pipeline and routes
    - Create `services/messaging_service.py` orchestrating validate → receiver-exists → moderate → (blocked halts with no persist/deliver/scam) → (flagged persists withheld and admin-visible) → (approved) scam score → persist → threshold≥70 warning + admin scam alert → deliver
    - Create `routers/messages.py` with `POST /api/messages`, `GET /api/messages/{userId}` (ascending history), and `GET /api/messages/stream` (SSE)
    - Implement SSE delivery to active sessions and retention for offline receivers
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 8.1, 8.3, 8.4, 8.5, 8.6_

  - [~] 9.2 Write property test for passing-message persistence round-trip
    - **Feature: ubuntu-connect, Property 22: For any message of 1–2000 characters that passes moderation and scam checks, it is persisted with sender_id, receiver_id, content, moderation_result, scam_score, and created_at, and reading it back yields the same values.**
    - **Validates: Requirements 6.1**

  - [~] 9.3 Write property test for conversation history ordering
    - **Feature: ubuntu-connect, Property 23: For any set of messages exchanged between two users, opening the conversation returns exactly those messages ordered by created_at ascending.**
    - **Validates: Requirements 6.3**

  - [~] 9.4 Write property test for message content-length validation
    - **Feature: ubuntu-connect, Property 24: For any submitted message whose content is empty or longer than 2000 characters, the message is rejected with a validation error identifying the content field.**
    - **Validates: Requirements 6.5**

  - [~] 9.5 Write property test for offline retention and later delivery
    - **Feature: ubuntu-connect, Property 25: For any message accepted for a receiver with no active session, the message is retained and appears when the receiver next opens the conversation.**
    - **Validates: Requirements 6.6**

  - [~] 9.6 Write property test for blocked-message pipeline halt
    - **Feature: ubuntu-connect, Property 27: For any message whose Moderation_Result is "blocked", the message is neither persisted nor delivered, scam detection is not invoked, and a content-policy error is returned.**
    - **Validates: Requirements 7.2**

  - [~] 9.7 Write property test for approved messages proceeding to scam detection
    - **Feature: ubuntu-connect, Property 28: For any message whose Moderation_Result is "approved", the scam detector is invoked.**
    - **Validates: Requirements 7.3**

  - [~] 9.8 Write property test for flagged-message persist-and-withhold
    - **Feature: ubuntu-connect, Property 29: For any message whose Moderation_Result is "flagged", the message is persisted with the flagged result, withheld from delivery to the receiver, and made available to the Admin_Panel.**
    - **Validates: Requirements 7.4**

  - [~] 9.9 Write property test for scam warning threshold at 70
    - **Feature: ubuntu-connect, Property 31: For any delivered message, a scam safety warning is attached if and only if its Scam_Score is 70 or greater.**
    - **Validates: Requirements 8.3, 8.5**

  - [~] 9.10 Write property test for high-scam admin alerts
    - **Feature: ubuntu-connect, Property 32: For any message with a Scam_Score of 70 or greater, a scam alert available to the Admin_Panel is created.**
    - **Validates: Requirements 8.4**

  - [~] 9.11 Write unit test for unknown recipient
    - Assert `GET`/send to a non-existent receiver returns a recipient-not-found error
    - _Requirements: 6.4_

  - [~] 9.12 Write integration test for SSE delivery within 2 seconds
    - Use a fake subscriber and controlled clock to assert an approved message reaches an active session within 2s of persistence
    - _Requirements: 6.2_

- [~] 10. Checkpoint - Ensure all backend service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement user reporting and admin panel
  - [~] 11.1 Implement ReportService and routes
    - Create `services/report_service.py` creating reports (reason 1–1000, status pending, created_at) and rejecting missing fields, self-reports, unknown reported users, over-length reasons, and duplicate pending reports
    - Create `routers/reports.py` for report submission
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [~] 11.2 Implement AdminService and routes behind role guard
    - Create `services/admin_service.py` (behind the admin guard) exposing flagged users, reports list with resolution accepting only confirmed/dismissed for pending reports, and scam alerts ≥70; on confirmed resolution trigger Trust Engine recalculation
    - Create `routers/admin.py` for flagged users, reports, resolution, and scam alerts
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [~] 11.3 Write property test for report creation defaults and validation
    - **Feature: ubuntu-connect, Property 42: For any report submission, when it identifies an existing other user and a reason of 1–1000 characters it creates a record with reporter, reported_user, reason, status "pending", and created_at; it is rejected identifying missing fields when reported_user or reason is absent, for self-reporting, and when the reason exceeds 1000 characters.**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.5**

  - [~] 11.4 Write property test for duplicate pending report rejection
    - **Feature: ubuntu-connect, Property 43: For any reporter with an existing pending report against a given user, a second report against that same user is rejected indicating a pending report already exists.**
    - **Validates: Requirements 12.6**

  - [~] 11.5 Write property test for admin route authorization
    - **Feature: ubuntu-connect, Property 37: For any request to an Admin_Panel route from a non-Administrator account, the request is rejected with an authorization error.**
    - **Validates: Requirements 11.1**

  - [~] 11.6 Write property test for flagged-users membership and ordering
    - **Feature: ubuntu-connect, Property 38: For any dataset, the flagged-users view lists exactly the users having at least one flagged message or at least one confirmed report, ordered by their most recent flagged message or confirmed report descending.**
    - **Validates: Requirements 11.2**

  - [~] 11.7 Write property test for reports view fields and ordering
    - **Feature: ubuntu-connect, Property 39: For any set of reports, the reports view shows each report's reporter, reported_user, reason, and status, ordered by created_at descending.**
    - **Validates: Requirements 11.3**

  - [~] 11.8 Write property test for report resolution validity
    - **Feature: ubuntu-connect, Property 40: For any pending report, resolving it with "confirmed" or "dismissed" updates its status to that decision; for any other decision value, the request is rejected identifying the accepted values and the status is unchanged.**
    - **Validates: Requirements 11.4, 11.5**

  - [~] 11.9 Write property test for scam alerts membership and ordering
    - **Feature: ubuntu-connect, Property 41: For any set of messages, the scam alerts view shows exactly the messages with a Scam_Score of 70 or greater, ordered by created_at descending.**
    - **Validates: Requirements 11.7**

  - [~] 11.10 Write unit tests for report-target and resolution edge cases
    - Assert unknown reported_user returns not-found (12.4) and resolving a missing/non-pending report is rejected leaving status unchanged (11.6)
    - _Requirements: 12.4, 11.6_

- [ ] 12. Implement Africa's Talking SMS gateway and notifications
  - [~] 12.1 Implement SmsGateway and NotificationService
    - Create `integrations/sms_gateway.py` wrapping the Africa's Talking SMS API for OTP, match notifications, and safety alerts using env-configured credentials
    - Create `services/notification_service.py` truncating notifications to ≤160 chars, delivering within 30s, retrying up to 3 additional times, and writing a `notification_failures` record (phone + type) when all attempts fail
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [~] 12.2 Write property test for SMS notification truncation
    - **Feature: ubuntu-connect, Property 50: For any match notification or safety alert, the text sent through the SMS_Gateway is truncated to 160 characters or fewer.**
    - **Validates: Requirements 14.1, 14.2**

  - [~] 12.3 Write property test for retry bound and failure recording
    - **Feature: ubuntu-connect, Property 51: For any notification whose delivery keeps failing, delivery is attempted at most 4 times total (initial plus 3 retries), and if all attempts fail a failure record is written capturing the target phone number and the notification type.**
    - **Validates: Requirements 14.3, 14.4**

  - [~] 12.4 Write integration test for SMS client request shaping and retries
    - Mock the Africa's Talking gateway and assert request shape plus retry behavior
    - _Requirements: 14.1, 14.3_

- [ ] 13. Implement USSD service
  - [~] 13.1 Implement UssdService and callback route
    - Create `integrations/ussd_gateway.py` menu/session helpers and `services/ussd_service.py` state machine keyed on the session `text`: unregistered→register option; registered→view profile / view trust / inbox preview; register with non-empty name creates user (verified_phone false, trust_score 0) and triggers OTP; empty name returns in-session error; profile uses placeholders for empty bio/interests; trust returns current score; inbox returns ≤5 recent with sender name + 40-char preview or empty message; invalid selection re-shows menu
    - Create `routers/ussd.py` handling the Africa's Talking USSD session callback
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9_

  - [~] 13.2 Write property test for USSD menu by registration state
    - **Feature: ubuntu-connect, Property 44: For any USSD session, an unregistered phone is offered a register option, and a registered user is offered view-profile, view-trust-score, and inbox-preview options.**
    - **Validates: Requirements 13.1, 13.2**

  - [~] 13.3 Write property test for USSD registration creating a user and triggering OTP
    - **Feature: ubuntu-connect, Property 45: For any non-empty full name provided over USSD for an unregistered phone, a user record is created with verified_phone false and trust_score 0 and OTP delivery is triggered through the SMS_Gateway.**
    - **Validates: Requirements 13.3**

  - [~] 13.4 Write property test for USSD profile placeholders
    - **Feature: ubuntu-connect, Property 46: For any registered user, the USSD view-profile response includes the full name and returns a placeholder wherever the bio or interests are empty.**
    - **Validates: Requirements 13.5**

  - [~] 13.5 Write property test for USSD trust score view
    - **Feature: ubuntu-connect, Property 47: For any registered user, the USSD view-trust-score response includes that user's current Trust_Score.**
    - **Validates: Requirements 13.6**

  - [~] 13.6 Write property test for USSD inbox preview limit and truncation
    - **Feature: ubuntu-connect, Property 48: For any registered user's messages, the USSD inbox preview returns at most the 5 most recent, each showing the sender name and a content preview truncated to 40 characters.**
    - **Validates: Requirements 13.7**

  - [~] 13.7 Write property test for USSD invalid selection re-showing menu
    - **Feature: ubuntu-connect, Property 49: For any menu selection not offered in the current USSD menu, the service returns the current menu again with a message indicating the selection is not valid.**
    - **Validates: Requirements 13.9**

  - [~] 13.8 Write unit tests for empty inbox and empty-name register
    - Assert empty-inbox message (13.8) and empty-name in-session error (13.4)
    - _Requirements: 13.8, 13.4_

- [~] 14. Checkpoint - Ensure all backend and integration tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Scaffold frontend, design system, and theme tokens
  - [~] 15.1 Set up Next.js app, Tailwind theme, and design tokens
    - Scaffold the Next.js 15 App Router project with TypeScript, Tailwind, shadcn/ui, React Hook Form, and fast-check
    - Define theme tokens: palette (primary #0F766E, secondary #134E4A, background #FAFAFA, text #111827, accent #F59E0B), Inter typeface, spacing scale in multiples of 8px, and transition durations ≤200ms; export tokens as typed constants for testability
    - Configure a fast-check test setup with min 100 runs
    - _Requirements: 18.1, 18.2, 18.3, 17.3, 17.5, 17.6_

  - [~] 15.2 Write property test for 8px spacing tokens
    - **Feature: ubuntu-connect, Property 55: For any layout margin, padding, or gap value used by the frontend, the value is a whole multiple of 8 pixels.**
    - **Validates: Requirements 17.3**

  - [~] 15.3 Write property test for text contrast ≥4.5:1
    - **Feature: ubuntu-connect, Property 56: For any text/background color-token pair used for normal-size text, the contrast ratio is at least 4.5:1.**
    - **Validates: Requirements 17.5**

  - [~] 15.4 Write property test for transition durations ≤200ms
    - **Feature: ubuntu-connect, Property 58: For any interface transition token, its duration is 200 milliseconds or less.**
    - **Validates: Requirements 18.3**

  - [~] 15.5 Write unit tests for palette and typeface application
    - Assert theme applies the specified palette and Inter typeface tokens
    - _Requirements: 18.1, 18.2_

- [ ] 16. Implement shared hooks and feedback components
  - [~] 16.1 Implement shared hooks
    - Create `hooks/useAuth.ts`, `hooks/useAsyncResource.ts` (idle→loading→success|empty|error|timeout with 30s timeout and retry), `hooks/useMessageStream.ts` (SSE subscription), `hooks/useTrustScore.ts`, and `hooks/useToast.ts`, each consumed by 2+ components/pages
    - _Requirements: 15.2, 16.3, 16.4, 16.5, 16.6_

  - [~] 16.2 Implement feedback components
    - Create `components/feedback/LoadingState.tsx`, `EmptyState.tsx`, and `ErrorState.tsx` (with retry action), plus a focus-indicator utility and ≥44x44 touch-target styling for small viewports
    - _Requirements: 16.3, 16.4, 16.5, 16.6, 17.4, 17.6_

  - [~] 16.3 Write property test for touch targets ≥44x44 on small viewports
    - **Feature: ubuntu-connect, Property 57: For any interactive element rendered at a viewport width of 640 pixels or less, its touch target is at least 44 by 44 pixels.**
    - **Validates: Requirements 17.6**

  - [~] 16.4 Write unit tests for async states and focus indicators
    - Test loading/empty/error/timeout renders and visible focus indicators on interactive elements
    - _Requirements: 16.3, 16.4, 16.5, 16.6, 17.4_

- [ ] 17. Implement trust and chat presentation components
  - [~] 17.1 Implement TrustScoreBadge and TrustReasonList
    - Create `components/trust/TrustScoreBadge.tsx` showing an integer [0,100] score, rendered with accent #F59E0B iff score ≥70, and `components/trust/TrustReasonList.tsx`
    - _Requirements: 18.4, 18.5, 18.6, 5.7_

  - [~] 17.2 Implement chat message components
    - Create `components/chat/MessageBubble.tsx`, `ScamWarning.tsx` (rendered adjacent to content iff message carries the warning), `CautionIndicator.tsx` (shown iff partner Trust_Score < 30), and `MessageComposer.tsx`; plus `components/conversation/ConversationList.tsx` and verified/unverified profile indicator
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [~] 17.3 Write property test for trust badge value and accent threshold
    - **Feature: ubuntu-connect, Property 59: For any displayed profile, the Trust_Score badge shows the user's score as an integer in [0, 100], and is rendered with the accent color #F59E0B if and only if the score is 70 or greater.**
    - **Validates: Requirements 18.4, 18.5, 18.6**

  - [~] 17.4 Write property test for scam warning rendering
    - **Feature: ubuntu-connect, Property 33: For any rendered message, the scam warning is displayed adjacent to the content if and only if the message carries the scam safety warning.**
    - **Validates: Requirements 9.1**

  - [~] 17.5 Write property test for caution indicator threshold at 30
    - **Feature: ubuntu-connect, Property 34: For any rendered conversation, a caution indicator is displayed if and only if the partner's Trust_Score is below 30.**
    - **Validates: Requirements 9.2, 9.3**

- [ ] 18. Implement authentication pages
  - [~] 18.1 Implement Login and Register (with OTP) pages
    - Create `app/(auth)/login/page.tsx` and `app/(auth)/register/page.tsx` (including the OTP verification step and resend), wired to auth endpoints via `useAuth` and `useAsyncResource`, applying single-column layout at ≤640px and two-column at >640px
    - _Requirements: 3.1, 3.2, 3.4, 1.1, 1.3, 2.3, 2.7, 17.1, 17.2_

  - [~] 18.2 Write unit tests for auth form validation and responsive layout
    - Test client-side field validation, OTP step flow, and single vs multi-column layout at the 640px breakpoint
    - _Requirements: 1.3, 2.3, 17.1, 17.2_

- [ ] 19. Implement dashboard and conversation views
  - [~] 19.1 Implement Dashboard page
    - Create `app/(app)/dashboard/page.tsx` showing up to 20 most recent conversations (desc by latest message), the user's Trust_Score with reasons, unread safety notifications, loading/empty/error+retry states, and unauthenticated redirect to login; use `useMessageStream`, `useTrustScore`, `useAsyncResource`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [~] 19.2 Write property test for dashboard conversation limit and ordering
    - **Feature: ubuntu-connect, Property 35: For any set of a user's conversations, the Dashboard displays at most the 20 most recent, ordered by each conversation's most recent message created_at descending.**
    - **Validates: Requirements 10.1**

  - [~] 19.3 Write property test for unread safety notifications only
    - **Feature: ubuntu-connect, Property 36: For any mix of read and unread safety notifications for a user, the Dashboard displays exactly the unread ones.**
    - **Validates: Requirements 10.3**

  - [~] 19.4 Write unit tests for dashboard trust display and unauthenticated redirect
    - Test Trust_Score + reasons presence and redirect-to-login for unauthenticated access
    - _Requirements: 10.2, 10.7_

- [ ] 20. Implement remaining pages
  - [~] 20.1 Implement Profile, Chat, Trust Details, Notifications, and Settings pages
    - Create `app/(app)/profile/[id]/page.tsx` (badge + verified indicator), `app/(app)/chat/[userId]/page.tsx` (history asc, live SSE, scam warnings, caution indicator), `app/(app)/trust/page.tsx` (score + reasons), `app/(app)/notifications/page.tsx` (unread safety notifications), and `app/(app)/settings/page.tsx` (bio/interests/photo editing), reusing shared hooks and feedback components
    - _Requirements: 4.1, 4.3, 4.5, 4.8, 5.7, 6.2, 6.3, 9.1, 9.2, 9.4, 10.3_

  - [~] 20.2 Implement Admin page
    - Create `app/(admin)/admin/page.tsx` with flagged users, reports with resolve action, and scam alerts, guarded so non-admins are rejected
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.7_

  - [~] 20.3 Write unit tests for chat ordering and admin view rendering
    - Test ascending chat history rendering and admin flagged/reports/scam-alert lists
    - _Requirements: 6.3, 11.2, 11.3, 11.7_

- [ ] 21. Wire everything together and add structural tests
  - [~] 21.1 Wire frontend to backend and finalize app assembly
    - Connect all pages to backend endpoints, register routers in `main.py`, configure the API client with the 30s timeout contract, and ensure the SSE stream is consumed by chat and dashboard
    - _Requirements: 6.2, 16.6, 15.6_

  - [~] 21.2 Write smoke/architecture tests
    - Repository boundary: no module under `services/` imports `sqlalchemy` (15.1); shared hooks imported by 2+ components (15.2); moderation/scam are separate modules with independent prompt modules (15.3); no hardcoded credentials/endpoints (15.4); OpenAPI defines request and response models for every route (15.6)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

  - [~] 21.3 Write end-to-end pipeline integration test
    - With a stubbed OpenAI returning each label/score band, assert persistence, delivery, warnings, and admin alerts together across the full message pipeline
    - _Requirements: 6.1, 7.2, 7.3, 7.4, 8.3, 8.4_

- [~] 22. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, though they encode the 59 correctness properties and boundary/structural guarantees.
- Each of the 59 design properties maps to exactly one property test tagged `Feature: ubuntu-connect, Property {number}: {property_text}`, running a minimum of 100 generated examples (Hypothesis on the backend, fast-check on the frontend).
- The OpenAI client is mocked in property tests so orchestration, thresholds, and fallbacks are exercised rather than the provider.
- OTP (task 5) depends on the SMS gateway interface; a stub interface is introduced with OTP and fully implemented in task 12.
- Checkpoints (tasks 10, 14, 22) provide incremental validation points.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.1", "8.1", "8.2", "12.1"] },
    { "id": 3, "tasks": ["2.3", "3.2", "3.3", "4.1", "8.3", "12.2", "12.3", "12.4"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "5.1", "6.1", "7.1", "8.4", "8.5", "8.6"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "6.2", "6.3", "6.4", "6.5", "7.2", "7.3", "7.4", "7.5", "7.6", "9.1", "11.1", "11.2", "13.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10", "9.11", "9.12", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "11.9", "11.10", "13.2", "13.3", "13.4", "13.5", "13.6", "13.7", "13.8"] },
    { "id": 7, "tasks": ["15.1"] },
    { "id": 8, "tasks": ["15.2", "15.3", "15.4", "15.5", "16.1", "16.2"] },
    { "id": 9, "tasks": ["16.3", "16.4", "17.1", "17.2"] },
    { "id": 10, "tasks": ["17.3", "17.4", "17.5", "18.1", "19.1", "20.1", "20.2"] },
    { "id": 11, "tasks": ["18.2", "19.2", "19.3", "19.4", "20.3", "21.1"] },
    { "id": 12, "tasks": ["21.2", "21.3"] }
  ]
}
```

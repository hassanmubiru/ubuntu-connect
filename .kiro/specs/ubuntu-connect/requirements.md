# Requirements Document

## Introduction

Ubuntu Connect is an AI-powered trust platform for social networking across Africa. It is not a dating app; its purpose is to help people safely build genuine relationships and connections. The platform addresses four core problems: verifying user identity, scoring trustworthiness, detecting scams in communication, and providing inclusive access to people with limited internet through SMS and USSD channels.

The system is delivered as a Next.js web application backed by a FastAPI service with a PostgreSQL data store. Identity verification and inclusive access are powered by the Africa's Talking SMS and USSD APIs. Content moderation and scam detection are powered by the OpenAI API through a modular prompt architecture, with a rule-based fallback so protection continues when the AI provider is unavailable.

This document defines the functional and non-functional requirements for Ubuntu Connect, expressed in EARS patterns and validated against INCOSE quality rules.

## Glossary

- **Ubuntu_Connect**: The complete social networking trust platform, including web frontend, backend services, and integrations.
- **Auth_Service**: The backend component responsible for registration, credential handling, and JWT issuance.
- **OTP_Service**: The backend component that generates, sends, and validates one-time passwords.
- **SMS_Gateway**: The integration layer that sends and receives SMS through the Africa's Talking SMS API.
- **USSD_Service**: The integration layer that handles Africa's Talking USSD session callbacks and menu navigation.
- **Profile_Service**: The backend component that manages user profile data, including photo, bio, and interests.
- **Messaging_Service**: The backend component that stores, delivers, and streams chat messages between users.
- **Moderation_Service**: The AI-backed component that evaluates message content for harmful or policy-violating material before sending.
- **Scam_Detector**: The component that assigns a scam score to message content, using an OpenAI-based analyzer with a rule-based fallback.
- **Trust_Engine**: The backend component that calculates a user trust score and the reasons behind it.
- **Dashboard**: The authenticated web view that shows recent conversations, trust insights, and safety notifications.
- **Admin_Panel**: The privileged web view used by administrators to view flagged users, moderate reports, and review scam alerts.
- **OTP**: A one-time password, a numeric code sent to a user's phone to verify phone ownership.
- **JWT**: A JSON Web Token used to authenticate requests after login.
- **Trust_Score**: An integer from 0 to 100 representing a user's calculated trustworthiness.
- **Scam_Score**: An integer from 0 to 100 representing the estimated likelihood that a message is a scam.
- **Moderation_Result**: A classification label applied to a message by the Moderation_Service, one of "approved", "flagged", or "blocked".
- **Administrator**: A user account with elevated privileges to access the Admin_Panel.
- **Verified_Phone**: A boolean state indicating a user has completed OTP verification.

## Requirements

### Requirement 1: Phone Registration

**User Story:** As a new user, I want to register with my phone number, full name, and basic details, so that I can create an account on Ubuntu Connect.

#### Acceptance Criteria

1. WHEN a visitor submits a registration request with a full name of 2 to 100 characters and a phone number in E.164 format that does not belong to an existing user record, THE Auth_Service SHALL create a user record with verified_phone set to false and trust_score set to 0.
2. IF a registration request contains a phone number that already belongs to an existing user record, THEN THE Auth_Service SHALL reject the request, persist no new user record, and return an error indicating the phone number is already registered.
3. IF a registration request contains a phone number that does not match the E.164 format, THEN THE Auth_Service SHALL reject the request and return a validation error identifying the phone field.
4. IF a registration request omits the phone number, or omits the full name, or contains a full name that is empty or only whitespace, THEN THE Auth_Service SHALL reject the request and return a validation error identifying each missing field.
5. IF a registration request contains a full name shorter than 2 characters or longer than 100 characters, THEN THE Auth_Service SHALL reject the request and return a validation error identifying the full name field.
6. WHEN a user record is created, THE Auth_Service SHALL set the created_at field to the time the record is persisted.

### Requirement 2: OTP Verification via SMS

**User Story:** As a registering user, I want to receive a one-time password by SMS and confirm it, so that I can prove I own my phone number.

#### Acceptance Criteria

1. WHEN a user record is created, THE OTP_Service SHALL generate a 6-digit OTP and request delivery through the SMS_Gateway to the registered phone number.
2. WHEN the OTP_Service generates an OTP, THE OTP_Service SHALL store the OTP with an expiry time of 10 minutes after generation.
3. WHEN a user submits an OTP that matches the stored OTP and the current time is before the expiry time, THE OTP_Service SHALL set the user's verified_phone to true.
4. IF a user submits an OTP that does not match the stored OTP and fewer than 5 failed attempts have been recorded for that stored OTP, THEN THE OTP_Service SHALL reject the submission, record the failed attempt, and return an error indicating the code is incorrect.
5. IF a user submits an OTP that does not match the stored OTP and 5 failed attempts have already been recorded for that stored OTP, THEN THE OTP_Service SHALL invalidate the stored OTP, reject the submission, and return an error indicating the maximum number of attempts has been reached and that a new code must be requested.
6. IF a user submits an OTP after the expiry time, THEN THE OTP_Service SHALL reject the submission and return an error indicating the code has expired.
7. WHEN a user requests a new OTP and fewer than 5 OTP requests have been made for that user within the preceding 60 minutes, THE OTP_Service SHALL invalidate any previously stored OTP for that user, reset the failed attempt count, and generate a replacement OTP.
8. IF a user requests a new OTP and 5 OTP requests have already been made for that user within the preceding 60 minutes, THEN THE OTP_Service SHALL reject the request and return an error indicating the resend limit has been reached and the duration of the 60-minute window before a new request is permitted.
9. IF the SMS_Gateway returns a delivery failure, THEN THE OTP_Service SHALL return an error indicating the code could not be sent and SHALL allow the user to request the code again.

### Requirement 3: Login and Session Authentication

**User Story:** As a registered user, I want to log in and receive an authenticated session, so that I can access my account securely.

#### Acceptance Criteria

1. WHEN a user submits valid login credentials for an account whose verified_phone is true, THE Auth_Service SHALL issue a JWT that identifies the user and return the JWT in the login response.
2. IF a user submits login credentials for an account whose verified_phone is false, THEN THE Auth_Service SHALL reject the login and return an error indicating phone verification is required.
3. IF a user submits credentials that do not match any user record, THEN THE Auth_Service SHALL reject the login and return an authentication error.
4. IF a login request omits a required credential field, THEN THE Auth_Service SHALL reject the login and return a validation error identifying each missing field.
5. WHEN the Auth_Service issues a JWT, THE Auth_Service SHALL set the token to expire 24 hours after issuance.
6. IF a request to a protected endpoint includes no JWT, or includes an expired or invalid JWT, THEN THE Auth_Service SHALL reject the request and return an authentication error.

### Requirement 4: Profile Management

**User Story:** As a user, I want to manage my profile photo, bio, and interests, so that others can learn who I am and I can present myself genuinely.

#### Acceptance Criteria

1. WHEN an authenticated user submits a bio of 500 characters or fewer, THE Profile_Service SHALL save the bio to the user's record.
2. IF an authenticated user submits a bio longer than 500 characters, THEN THE Profile_Service SHALL reject the update and return a validation error identifying the bio field.
3. WHEN an authenticated user submits a list of no more than 20 interests, each 50 characters or fewer, THE Profile_Service SHALL save the interests to the user's record.
4. IF an authenticated user submits more than 20 interests or an interest longer than 50 characters, THEN THE Profile_Service SHALL reject the update, leave the existing interests unchanged, and return a validation error identifying the interests field.
5. WHEN an authenticated user uploads a profile photo in JPEG or PNG format that is 5 megabytes or smaller, THE Profile_Service SHALL store the photo and associate it with the user's record.
6. IF an authenticated user uploads a profile photo that is not JPEG or PNG, THEN THE Profile_Service SHALL reject the upload and return an error identifying the accepted formats.
7. IF an authenticated user uploads a profile photo larger than 5 megabytes, THEN THE Profile_Service SHALL reject the upload and return an error identifying the size limit.
8. WHEN a user profile is displayed, THE Profile_Service SHALL include the user's current Trust_Score and Verified_Phone state.

### Requirement 5: Trust Engine

**User Story:** As a user, I want a trust score that reflects verification, profile completeness, reports, and activity, so that I can gauge how trustworthy other users are and understand my own standing.

#### Acceptance Criteria

1. THE Trust_Engine SHALL calculate each Trust_Score as an integer between 0 and 100 inclusive.
2. WHEN a user's verified_phone becomes true, THE Trust_Engine SHALL recalculate that user's Trust_Score such that phone verification contributes a non-negative amount to the score.
3. WHEN a user updates their profile photo, bio, or interests, THE Trust_Engine SHALL recalculate that user's Trust_Score using profile completeness, measured as the count of the three profile fields (profile photo, bio, interests) that are populated, as a contributing factor.
4. WHEN a report against a user is resolved as confirmed, THE Trust_Engine SHALL recalculate that user's Trust_Score such that the recalculated score is lower than the score would be without the confirmed report.
5. THE Trust_Engine SHALL calculate each Trust_Score from four factors: phone verification, profile completeness, the count of confirmed reports against the user, and account activity measured as the count of messages the user has sent.
6. WHEN the Trust_Engine calculates a Trust_Score, THE Trust_Engine SHALL record a reason entry for each contributing factor describing that factor's effect on the score.
7. WHEN a user requests the explanation for a Trust_Score, THE Trust_Engine SHALL return the recorded reason entries for that score.
8. IF a user requests the explanation for a Trust_Score that has no recorded reason entries, THEN THE Trust_Engine SHALL return an error indicating no explanation is available.

### Requirement 6: Real-Time Messaging

**User Story:** As a user, I want to chat with another user in real time, so that I can build a connection conveniently.

#### Acceptance Criteria

1. WHEN an authenticated sender submits a message of 1 to 2000 characters to a receiver and the message passes moderation and scam checks, THE Messaging_Service SHALL persist the message with sender_id, receiver_id, content, moderation_result, scam_score, and created_at.
2. WHEN a message is persisted for delivery and the receiver has an active session, THE Messaging_Service SHALL stream the message to the receiver's active session within 2 seconds of persistence.
3. WHEN an authenticated user opens a conversation, THE Messaging_Service SHALL return the messages exchanged between the two users ordered by created_at ascending.
4. IF an authenticated user requests a conversation with a user record that does not exist, THEN THE Messaging_Service SHALL return an error indicating the recipient was not found.
5. IF an authenticated sender submits a message that is empty or longer than 2000 characters, THEN THE Messaging_Service SHALL reject the message and return a validation error identifying the content field.
6. IF a message is persisted for delivery and the receiver has no active session, THEN THE Messaging_Service SHALL retain the persisted message and deliver it when the receiver next opens the conversation.

### Requirement 7: AI Content Moderation

**User Story:** As a user, I want harmful messages to be caught before they are sent, so that conversations stay safe and respectful.

#### Acceptance Criteria

1. WHEN a sender submits a message, THE Moderation_Service SHALL evaluate the message content and assign a Moderation_Result of "approved", "flagged", or "blocked" before the message is delivered.
2. IF a message receives a Moderation_Result of "blocked", THEN THE Messaging_Service SHALL reject the message, neither persist nor deliver it, not proceed to scam detection, and return an error indicating the message violates content policy.
3. WHEN a message receives a Moderation_Result of "approved", THE Messaging_Service SHALL proceed to the scam detection check.
4. WHEN a message receives a Moderation_Result of "flagged", THE Messaging_Service SHALL persist the message with the "flagged" result, withhold the message from delivery to the receiver, and make the message available to the Admin_Panel for review.
5. WHERE the OpenAI API is unavailable, THE Moderation_Service SHALL apply the rule-based fallback to assign a Moderation_Result.
6. IF the OpenAI API does not respond within 5 seconds while moderating a message, THEN THE Moderation_Service SHALL apply the rule-based fallback to assign a Moderation_Result.

### Requirement 8: Scam Detection

**User Story:** As a user, I want messages checked for scam signals before they reach me, so that I am warned about likely fraud.

#### Acceptance Criteria

1. WHEN a message passes moderation, THE Scam_Detector SHALL assign a Scam_Score that is an integer from 0 to 100 inclusive to the message within 5 seconds and before the message is delivered.
2. IF the OpenAI API returns an error or does not respond within 3 seconds while scoring a message, THEN THE Scam_Detector SHALL assign the Scam_Score using the rule-based fallback.
3. WHEN a message has a Scam_Score of 70 or greater, THE Messaging_Service SHALL attach a safety warning to the delivered message identifying it as a likely scam.
4. WHEN a message has a Scam_Score of 70 or greater, THE Messaging_Service SHALL create a scam alert available to the Admin_Panel.
5. WHEN a message has a Scam_Score below 70, THE Messaging_Service SHALL deliver the message without a scam safety warning.
6. THE Scam_Detector SHALL store the assigned Scam_Score on the message record before the message is delivered.

### Requirement 9: Safety Warnings

**User Story:** As a user, I want clear safety warnings during conversations, so that I can make informed decisions about who to trust.

#### Acceptance Criteria

1. WHEN the Dashboard displays a message that carries a scam safety warning, THE Dashboard SHALL display a warning identifying the message as a likely scam adjacent to that message's content.
2. WHEN the Dashboard displays a conversation whose partner has a Trust_Score below 30, THE Dashboard SHALL display a caution indicator on that conversation.
3. WHEN the Dashboard displays a conversation whose partner has a Trust_Score of 30 or greater, THE Dashboard SHALL NOT display a caution indicator on that conversation.
4. WHEN a user views a conversation partner's profile, THE Dashboard SHALL display the partner's verified_phone state as a verified or unverified indicator.

### Requirement 10: Dashboard

**User Story:** As a user, I want a dashboard showing my recent conversations, trust insights, and safety notifications, so that I can stay oriented and safe at a glance.

#### Acceptance Criteria

1. WHEN an authenticated user opens the Dashboard, THE Dashboard SHALL display up to the user's 20 most recent conversations ordered by the created_at of each conversation's most recent message descending.
2. WHEN an authenticated user opens the Dashboard, THE Dashboard SHALL display the user's current Trust_Score and its recorded reason entries.
3. WHEN an authenticated user opens the Dashboard, THE Dashboard SHALL display unread safety notifications for that user.
4. WHILE the Dashboard is loading conversation data, THE Dashboard SHALL display a loading state.
5. IF an authenticated user has no conversations, THEN THE Dashboard SHALL display an empty state inviting the user to start a conversation.
6. IF loading the Dashboard conversation data fails, THEN THE Dashboard SHALL display an error state indicating the conversations could not be loaded and SHALL provide a retry action, preserving the user's session.
7. IF an unauthenticated request opens the Dashboard, THEN THE Dashboard SHALL reject the request and redirect the requester to the login view.

### Requirement 11: Admin Panel

**User Story:** As an administrator, I want to view flagged users, moderate reports, and review scam alerts, so that I can keep the community safe.

#### Acceptance Criteria

1. IF a request to the Admin_Panel comes from an account that is not an Administrator, THEN THE Admin_Panel SHALL reject the request and return an authorization error.
2. WHEN an Administrator opens the flagged users view, THE Admin_Panel SHALL display users who have at least one flagged message or at least one confirmed report, ordered by their most recent flagged message or confirmed report descending.
3. WHEN an Administrator opens the reports view, THE Admin_Panel SHALL display reports with reporter, reported_user, reason, and status, ordered by created_at descending.
4. WHEN an Administrator resolves a report with a decision of either "confirmed" or "dismissed", THE Admin_Panel SHALL update the report's status to that decision.
5. IF an Administrator submits a resolution decision that is not "confirmed" or "dismissed", THEN THE Admin_Panel SHALL reject the request, return a validation error identifying the accepted decision values, and leave the report's status unchanged.
6. IF an Administrator attempts to resolve a report that does not exist or whose status is not "pending", THEN THE Admin_Panel SHALL reject the request, return an error indicating the report cannot be resolved, and leave the report's status unchanged.
7. WHEN an Administrator opens the scam alerts view, THE Admin_Panel SHALL display messages with a Scam_Score of 70 or greater ordered by created_at descending.

### Requirement 12: User Reporting

**User Story:** As a user, I want to report another user for concerning behavior, so that administrators can investigate and protect the community.

#### Acceptance Criteria

1. WHEN an authenticated user submits a report identifying an existing reported_user and a reason of between 1 and 1000 characters, THE Ubuntu_Connect SHALL create a report record with reporter set to the submitting user, reported_user, reason, status set to "pending", and created_at set to the time the record is persisted.
2. IF a report submission omits the reported_user or the reason, THEN THE Ubuntu_Connect SHALL reject the submission and return a validation error identifying each missing field.
3. IF an authenticated user submits a report identifying themselves as the reported_user, THEN THE Ubuntu_Connect SHALL reject the submission and return an error indicating self-reporting is not permitted.
4. IF a report submission identifies a reported_user that does not match any existing user record, THEN THE Ubuntu_Connect SHALL reject the submission and return an error indicating the reported user was not found.
5. IF a report submission contains a reason longer than 1000 characters, THEN THE Ubuntu_Connect SHALL reject the submission and return a validation error identifying the reason field.
6. IF an authenticated user submits a report against a reported_user for whom that user already has a report with status "pending", THEN THE Ubuntu_Connect SHALL reject the submission and return an error indicating a pending report already exists.

### Requirement 13: USSD Access

**User Story:** As a user with limited internet access, I want to use core features over USSD, so that I can participate on any mobile phone.

#### Acceptance Criteria

1. WHEN the USSD_Service receives a session request from an unregistered phone number, THE USSD_Service SHALL present a menu option to register.
2. WHEN a registered user starts a USSD session, THE USSD_Service SHALL present a menu offering view profile, view trust score, and inbox preview options.
3. WHEN a user selects the register option over USSD and provides a non-empty full name, THE USSD_Service SHALL create a user record for the session phone number with verified_phone set to false and trust_score set to 0, and trigger OTP delivery through the SMS_Gateway.
4. IF a user selects the register option over USSD and provides an empty full name, THEN THE USSD_Service SHALL return an error message within the session response indicating the full name is required.
5. WHEN a registered user selects the view profile option over USSD, THE USSD_Service SHALL return the user's full name, bio, and interests within the session response, returning a placeholder where the bio or interests are empty.
6. WHEN a registered user selects the view trust score option over USSD, THE USSD_Service SHALL return the user's current Trust_Score within the session response.
7. WHEN a registered user selects the inbox preview option over USSD, THE USSD_Service SHALL return, for up to the 5 most recent messages, the sender name and a content preview truncated to 40 characters within the session response.
8. WHEN a registered user selects the inbox preview option over USSD and has no messages, THE USSD_Service SHALL return a message within the session response indicating the inbox is empty.
9. IF a user submits a menu selection that is not offered in the current USSD menu, THEN THE USSD_Service SHALL return the current menu again with a message indicating the selection is not valid.

### Requirement 14: SMS Notifications

**User Story:** As a user, I want to receive important notifications by SMS, so that I stay informed even without internet access.

#### Acceptance Criteria

1. WHEN a new match notification is generated for a user, THE SMS_Gateway SHALL send the notification, truncated to 160 characters or fewer, to that user's registered phone number within 30 seconds of the notification being generated.
2. WHEN a safety alert is generated for a user, THE SMS_Gateway SHALL send the alert, truncated to 160 characters or fewer, to that user's registered phone number within 30 seconds of the alert being generated.
3. IF the SMS_Gateway returns a delivery failure for a notification, THEN THE SMS_Gateway SHALL retry delivery up to 3 additional times before treating the notification as undeliverable.
4. IF all delivery attempts for a notification fail, THEN THE Ubuntu_Connect SHALL record the failure with the target phone number and the notification type.

### Requirement 15: Architecture and Code Organization

**User Story:** As a developer, I want a clean, modular codebase, so that the platform is maintainable and testable.

#### Acceptance Criteria

1. THE Ubuntu_Connect backend SHALL access all persisted data through repository components, and business logic components SHALL NOT issue direct data store queries.
2. THE Ubuntu_Connect frontend SHALL compose each interface view from named UI components, and SHALL encapsulate shared stateful logic in hooks that are each used by two or more components.
3. THE Ubuntu_Connect SHALL implement AI moderation and scam detection as separate service modules, with each service's prompts defined in a prompt module that is independent of the service's calling logic.
4. THE Ubuntu_Connect SHALL read all external service credentials and endpoints from environment variables, and SHALL NOT contain any external service credential or endpoint as a literal value in source code.
5. IF a required external service credential or endpoint environment variable is absent when the Ubuntu_Connect backend starts, THEN THE Ubuntu_Connect backend SHALL halt startup without serving requests and SHALL emit an error identifying each missing environment variable.
6. THE Ubuntu_Connect backend SHALL expose API documentation that describes, for every exposed endpoint, both its request schema and its response schema.

### Requirement 16: Input Validation and Error Handling

**User Story:** As a user, I want clear feedback when something goes wrong, so that I know how to proceed.

#### Acceptance Criteria

1. WHEN a request contains input that fails validation, THE Ubuntu_Connect SHALL reject the request, exclude any changes from the data store, and return an error response that identifies each invalid field and, for each field, the reason it failed validation.
2. IF a backend operation raises an unhandled exception, THEN THE Ubuntu_Connect SHALL return an error response with a generic message, SHALL exclude internal implementation details from the response, and SHALL leave previously persisted data unchanged.
3. WHILE the frontend is awaiting a backend response, THE Ubuntu_Connect frontend SHALL display a loading state for the affected view.
4. WHERE a view has no data to display, THE Ubuntu_Connect frontend SHALL display an empty state describing the absence of data.
5. IF a backend request returns an error response, THEN THE Ubuntu_Connect frontend SHALL stop displaying the loading state for the affected view and display an error state that describes the failure and offers a retry action.
6. IF the frontend does not receive a backend response within 30 seconds of issuing a request, THEN THE Ubuntu_Connect frontend SHALL stop displaying the loading state for the affected view and display an error state indicating the request timed out and offering a retry action.

### Requirement 17: Responsive and Accessible Layout

**User Story:** As a user on any device, I want a layout that adapts to my screen, so that I can use the platform comfortably.

#### Acceptance Criteria

1. WHILE the viewport width is 640 pixels or less, THE Ubuntu_Connect frontend SHALL present a single-column layout in which all primary content sections stack vertically.
2. WHILE the viewport width is greater than 640 pixels, THE Ubuntu_Connect frontend SHALL present a Dashboard layout of two or more columns.
3. THE Ubuntu_Connect frontend SHALL set all layout margins, padding, and gaps to values that are whole multiples of 8 pixels.
4. THE Ubuntu_Connect frontend SHALL display a visible focus indicator on every interactive element when it receives keyboard focus.
5. THE Ubuntu_Connect frontend SHALL maintain a contrast ratio of at least 4.5:1 between text and its background for normal-size text.
6. WHILE the viewport width is 640 pixels or less, THE Ubuntu_Connect frontend SHALL render interactive touch targets with a minimum size of 44 by 44 pixels.

### Requirement 18: Design System

**User Story:** As a user, I want a modern, minimal, professional interface, so that the platform feels trustworthy and handcrafted rather than generic.

#### Acceptance Criteria

1. THE Ubuntu_Connect frontend SHALL apply the color palette with primary #0F766E, secondary #134E4A, background #FAFAFA, text #111827, and accent #F59E0B.
2. THE Ubuntu_Connect frontend SHALL apply the Inter typeface to interface text.
3. THE Ubuntu_Connect frontend SHALL limit interface motion to transitions with a duration of 200 milliseconds or less.
4. WHEN a user profile is displayed, THE Ubuntu_Connect frontend SHALL present a Trust_Score badge showing that user's current Trust_Score as an integer from 0 to 100.
5. WHERE a displayed Trust_Score is 70 or greater, THE Ubuntu_Connect frontend SHALL render the Trust_Score badge using the accent color #F59E0B.
6. WHERE a displayed Trust_Score is less than 70, THE Ubuntu_Connect frontend SHALL render the Trust_Score badge without the accent color #F59E0B.

## Appendix A: Example Data

These examples illustrate realistic platform data and are provided to ground the requirements above.

**Example users**

- Amara Okafor — phone +2348031234567, interests: Afrobeats production, community gardening, mentoring. Trust_Score 82, verified_phone true.
- Thandiwe Nkosi — phone +27821234567, interests: hiking the Drakensberg, isiZulu poetry, small-business networking. Trust_Score 74, verified_phone true.
- Kwame Mensah — phone +233201234567, interests: chess, fintech meetups, amateur football coaching. Trust_Score 58, verified_phone true.
- Zainab Abdullahi — phone +254712345678, interests: Swahili literature, solar energy projects, choir. Trust_Score 25, verified_phone false.

**Example message (flagged for scam)**

- sender_id: Kwame Mensah, receiver_id: Amara Okafor, content: "I need you to send airtime to unlock your prize before midnight." moderation_result: "approved", scam_score: 88. The Messaging_Service attaches a safety warning and creates a scam alert for the Admin_Panel.

**Example report**

- reporter: Thandiwe Nkosi, reported_user: Kwame Mensah, reason: "Requested money under false pretenses.", status: "pending".

**Example USSD session (view trust score)**

- Session phone +254712345678 selects "3. View Trust Score"; the USSD_Service responds "Your Ubuntu Connect trust score is 25. Verify your phone to raise it."

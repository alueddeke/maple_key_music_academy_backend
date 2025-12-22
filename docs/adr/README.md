# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for the Maple Key Music Academy backend.

## What are ADRs?

Architecture Decision Records document significant architectural choices made in the project, including:
- The context and problem being addressed
- Alternatives considered
- The decision made and why
- Consequences (positive, negative, and neutral)
- When to revisit the decision

ADRs help maintain project knowledge, onboard new team members, and provide interview preparation material by documenting the "why" behind architectural choices.

## Decision Log

| ADR | Title | Status | Date | Tags |
|-----|-------|--------|------|------|
| [BE-0001](BE-0001-unified-user-model.md) | Unified User Model | Accepted | 2024-08-20 | #database-design #model-design #inheritance-vs-composition |
| [BE-0002](BE-0002-email-based-authentication.md) | Email-Based Authentication | Accepted | 2024-08-20 | #authentication #database-design #api-design |
| [BE-0003](BE-0003-dual-purpose-invoice-model.md) | Dual-Purpose Invoice Model | Accepted | 2024-09-15 | #model-design #dual-purpose-pattern #payment-processing |
| [BE-0004](BE-0004-dual-rate-lesson-pricing.md) | Dual-Rate Lesson Pricing | Accepted | 2024-10-05 | #payment-processing #rate-locking #data-integrity |
| [BE-0005](BE-0005-jwt-token-authentication.md) | JWT Token Authentication | Accepted | 2024-08-25 | #authentication #jwt #api-design #security |
| [BE-0006](BE-0006-oauth-with-django-allauth.md) | OAuth with Django Allauth | Accepted | 2024-09-01 | #oauth #authentication #third-party-integration |
| [BE-0007](BE-0007-pre-push-migration-hook.md) | Pre-Push Migration Hook | Accepted | 2024-11-20 | #migration-safety #workflow-automation #developer-experience |
| [BE-0008](BE-0008-student-billing-contact-design.md) | Student Billing Contact Design | Accepted | 2024-08-20 | #database-design #model-design #data-integrity |

## How to Create a New ADR

### When to Create an ADR

Create an ADR whenever you make a significant decision about:
- **Architecture patterns** (e.g., adding microservices, event sourcing)
- **Technology choices** (e.g., switching to GraphQL, adding Redis)
- **Data modeling** (e.g., new entity relationships, schema changes)
- **Authentication/Security** (e.g., adding 2FA, changing token strategy)
- **API design** (e.g., versioning strategy, pagination approach)
- **Performance optimizations** (e.g., caching layer, query optimization strategy)

### Workflow

1. **Copy the template:** `cp TEMPLATE.md BE-XXXX-your-decision-title.md`
2. **Number sequentially:** Use the next available number (BE-0009, BE-0010, etc.)
3. **Fill in all sections:** Context, Decision Drivers, Options, Decision, Consequences, Validation
4. **Add interview tags:** Include 3-5 relevant topic tags (see taxonomy below)
5. **Update this README:** Add your ADR to the decision log table
6. **Include in feature branch:** Commit the ADR with your feature implementation

### Example

```bash
# During feature development
git checkout -b feature/stripe-payment-integration

# Implement feature...

# Create ADR
cp docs/adr/TEMPLATE.md docs/adr/BE-0009-stripe-payment-integration.md
# Fill in ADR content...

# Commit together
git add src/payments/
git add docs/adr/BE-0009-stripe-payment-integration.md
git add docs/adr/README.md  # Update decision log
git commit -m "Add Stripe payment integration

- Implement Stripe payment processor
- Document decision in BE-0009 ADR
- Update decision log"
```

## Interview Topic Tags

Tags help categorize decisions by interview topics. Use 3-5 tags per ADR:

- `#authentication` - User authentication mechanisms
- `#authorization` - Permissions and access control
- `#database-design` - Database schema and modeling
- `#api-design` - REST API patterns and conventions
- `#security` - Security patterns and practices
- `#scalability` - System growth and performance
- `#developer-experience` - DX and workflow optimization
- `#payment-processing` - Financial transactions
- `#audit-trail` - Tracking and accountability
- `#rate-locking` - Financial stability patterns
- `#workflow-automation` - Process automation
- `#dual-purpose-pattern` - Multi-use model/entity design
- `#testing` - Testing strategies
- `#deployment` - CI/CD and production
- `#migration-safety` - Database migration best practices
- `#oauth` - OAuth2 implementation
- `#jwt` - JSON Web Token patterns
- `#model-design` - Domain modeling patterns
- `#inheritance-vs-composition` - OOP design patterns
- `#third-party-integration` - External service integration
- `#caching` - Performance optimization
- `#error-handling` - Error management patterns
- `#data-integrity` - Data consistency patterns

## Cross-References

- **Project Documentation:** See [CLAUDE.md](../../CLAUDE.md) for system architecture overview
- **Frontend ADRs:** [maple-key-music-academy-frontend/docs/adr/](../../maple-key-music-academy-frontend/docs/adr/README.md)
- **Docker ADRs:** [maple_key_music_academy_docker/docs/adr/](../../maple_key_music_academy_docker/docs/adr/README.md)

## Status Legend

- **Proposed:** Decision under review, not yet implemented
- **Accepted:** Final decision, implemented in the codebase
- **Deprecated:** No longer applicable or in use
- **Superseded:** Replaced by a newer ADR (link to replacement)

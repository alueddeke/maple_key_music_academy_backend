# ADR-BE-0008: Store Student Billing Contact Information Directly on User Model

**Status:** Accepted

**Date:** 2024-08-20

**Deciders:** Antoni

**Tags:** #database-design #model-design #data-integrity #payment-processing #scalability

**Technical Story:** Student billing contact information design

---

## Context and Problem Statement

Students taking lessons need billing contact information for invoices - typically a parent or guardian who pays for the lessons. We need to decide how to model this billing contact relationship: should billing contact information be stored directly on the User model, or should we create a separate BillableContact model with a one-to-many relationship?

**Key Questions:**
- How do we store parent/guardian billing information for students?
- Should we support multiple billing contacts per student?
- What's the right balance between simplicity (current needs) and flexibility (future needs)?
- How do we handle students who are adults and pay for themselves?

---

## Decision Drivers

* **Current requirements** - Most students have one billing contact (parent)
* **Simplicity** - Small team (2 developers), avoid over-engineering
* **Development velocity** - Launch quickly with MVP feature set
* **Data integrity** - Ensure students always have valid billing information
* **Future flexibility** - Easy to enhance if requirements change
* **Code maintainability** - Minimize model complexity

---

## Considered Options

* **Option 1:** **Store parent_email and parent_phone directly on User model** (CHOSEN)
* **Option 2:** Separate BillableContact model with one-to-many relationship
* **Option 3:** JSON field for flexible contact information
* **Option 4:** Third-party billing service integration (Stripe Customer Portal)

---

## Decision Outcome

**Chosen option:** "Store parent_email and parent_phone directly on User model"

**Rationale:**
For the initial implementation, we store billing contact information as `parent_email` and `parent_phone` fields directly on the `User` model (for student-type users). This simple approach meets current requirements where 95% of students have a single billing contact (parent). The fields are nullable and optional, allowing for students who are adults and pay for themselves. This avoids the complexity of a separate BillableContact model while we validate product-market fit.

### Consequences

**Positive:**
* **Simple implementation:** Two fields, no additional models or relationships
* **Fast queries:** No JOINs needed to get student billing information
* **Easy validation:** Built-in model validation, no separate queryset complexity
* **Sufficient for MVP:** Meets current needs for single billing contact per student
* **Clear migration path:** Can add BillableContact model later if needed

**Negative:**
* **Single contact limitation:** Can't represent multiple billing contacts (divorced parents, split billing)
* **Limited metadata:** Only email and phone, no address/payment preferences
* **No contact history:** Can't track when billing contact changes
* **Type coupling:** Billing contact fields exist on User model even for teachers/management

**Neutral:**
* **Self-billing students:** Empty fields for adult students who pay themselves (acceptable)
* **Field naming:** `parent_email/phone` is technically inaccurate for adult students (minor)

---

## Detailed Analysis of Options

### Option 1: Direct Fields on User Model (CHOSEN)

**Description:**
Add `parent_email` and `parent_phone` CharField fields to User model (nullable, for students only).

**Pros:**
* **Simplest implementation:** ~2 fields, 1 migration
* **No query overhead:** No JOINs
* **Easy to validate:** Standard model validation
* **Sufficient for current needs:** 95% of students have single parent contact

**Cons:**
* Can't represent multiple billing contacts
* Limited to email and phone (no address, payment method)
* Field name assumes parent (not guardian, self, etc.)

**Implementation Effort:** Very Low

**Code Reference:** `billing/models.py:60-61`

### Option 2: Separate BillableContact Model

**Description:**
Create `BillableContact` model with ForeignKey to Student, supports one-to-many relationship.

**Pros:**
* **Flexible:** Multiple billing contacts per student (divorced parents)
* **Rich metadata:** Full name, address, phone, email, payment preferences
* **Contact types:** Can distinguish parent, guardian, self, other
* **Primary contact flag:** Designate which contact receives invoices
* **History tracking:** Audit trail of contact changes

**Cons:**
* **Over-engineering:** Unnecessary complexity for current requirements (95% single contact)
* **Query overhead:** Always need JOIN to get billing info
* **More code:** Additional model, serializers, views, frontend forms (~200 lines)
* **Validation complexity:** Must ensure at least one primary contact

**Implementation Effort:** Medium (~4 hours)

**Note:** This may be implemented in the future if requirements change

### Option 3: JSON Field for Contacts

**Description:**
Store contacts as JSON array in `billing_contacts` JSONField on User.

**Pros:**
* Flexible schema
* Can add fields without migrations
* Supports multiple contacts

**Cons:**
* **No database validation:** Can't enforce constraints
* **Query complexity:** Can't easily filter/search billing contacts
* **No referential integrity:** Can't use ForeignKeys
* **Harder to maintain:** Schema in code, not database

**Implementation Effort:** Low but problematic

### Option 4: Third-Party Billing Integration

**Description:**
Use Stripe Customer Portal or similar for all billing contact management.

**Pros:**
* Delegate billing to experts
* PCI compliance handled
* Payment methods managed

**Cons:**
* **Vendor lock-in:** Dependent on external service
* **Overkill:** We're not charging automatically yet
* **Complexity:** OAuth, webhooks, sync issues
* **Cost:** $0.29 per transaction + 2.9%

**Implementation Effort:** High

---

## Validation

**How we'll know this decision was right:**
* **Coverage:** >90% of students represented with current fields (ACHIEVED: 98%)
* **Support burden:** <5% billing contact issues (complaints about multiple contacts)
* **Development velocity:** Billing features ship without contact model blocking
* **Migration feasibility:** If we need BillableContact, migration path is clear

**When to revisit this decision:**
* **If >20% of students need multiple billing contacts:** Divorced parents, split billing becoming common
* **If we need rich billing metadata:** Address, payment method, invoice delivery preferences required
* **If we implement automatic billing:** Stripe/payment processor integration requires customer objects
* **If contact history becomes critical:** Need audit trail of who paid when

---

## Links

* Implementation: `billing/models.py:60-61` - `parent_email`, `parent_phone` fields on User
* Related ADR: [BE-0001: Unified User Model](BE-0001-unified-user-model.md) - User model design
* Related ADR: [BE-0003: Dual-Purpose Invoice Model](BE-0003-dual-purpose-invoice-model.md) - Invoice generation
* Future consideration: Separate BillableContact model (if requirements change)

---

## Notes

**Current Implementation:**
```python
class User(AbstractUser):
    # ... core fields ...

    # Student-specific fields (nullable for teachers/management)
    assigned_teacher = models.ForeignKey('self', ...)
    parent_email = models.EmailField(blank=True)  # Billing contact email
    parent_phone = models.CharField(max_length=15, blank=True)  # Billing contact phone
```

**Usage in Invoicing:**
```python
# Generate student invoice
invoice = Invoice.objects.create(
    invoice_type='student_billing',
    student=student,  # User with user_type='student'
)

# Billing contact info for invoice PDF
billing_email = student.parent_email or student.email  # Fallback to student email
billing_phone = student.parent_phone or student.phone_number
```

**Self-Paying Students:**
```python
# Adult students (paying for themselves)
adult_student = User.objects.create(
    user_type='student',
    email='student@gmail.com',
    parent_email='',  # Empty - student pays themselves
    parent_phone='',
)
# Invoice sent to student.email
```

**Future BillableContact Model (if needed):**
```python
# POTENTIAL future implementation (not yet needed)
class BillableContact(models.Model):
    CONTACT_TYPES = [
        ('parent', 'Parent'),
        ('guardian', 'Guardian'),
        ('self', 'Self'),
        ('other', 'Other'),
    ]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='billable_contacts')
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPES)

    # Full contact information
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=15)

    # Address
    street_address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    zip_code = models.CharField(max_length=10)

    # Invoice preferences
    is_primary = models.BooleanField(default=False)  # Primary contact receives invoices
    invoice_delivery = models.CharField(choices=[('email', 'Email'), ('mail', 'Postal Mail')])
    payment_method = models.CharField(choices=[('check', 'Check'), ('card', 'Credit Card'), ...])

    def save(self, *args, **kwargs):
        # Ensure exactly one primary contact per student
        if self.is_primary:
            BillableContact.objects.filter(student=self.student, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)
```

**Migration Path (if we implement BillableContact):**
```python
# Data migration to preserve existing contacts
for student in User.objects.filter(user_type='student'):
    if student.parent_email or student.parent_phone:
        BillableContact.objects.create(
            student=student,
            contact_type='parent',
            email=student.parent_email or '',
            phone=student.parent_phone or '',
            is_primary=True,
        )
```

**Measured Impact:**
- Students with single billing contact: 98% (exceeds 90% threshold)
- Support tickets about multiple contacts: 2 in 6 months (<5% target)
- Development time saved: ~4 hours (BillableContact not needed yet)
- Query performance: No JOINs needed (8ms avg to get student + billing info)

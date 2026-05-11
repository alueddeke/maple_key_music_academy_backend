# custom_auth/views/__init__.py
# Re-export all public view functions so that custom_auth/urls.py can continue
# to use `from . import views` and `views.function_name` without any change.

from .oauth import google_exchange

from .registration import register_with_email

from .jwt_auth import (
    get_jwt_token,
    refresh_jwt_token,
)

from .profile import (
    user_profile,
    logout,
)

from .password_reset import (
    password_reset_request,
    password_reset_validate_token,
    password_reset_confirm,
)

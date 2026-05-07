from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import exceptions
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication


ACCOUNT_STATUS_MESSAGE = "Account is inactive or pending deletion."


def user_has_valid_account_status(user):
    if not user or not user.is_active:
        return False

    try:
        settings_profile = user.availability_settings_profile
    except ObjectDoesNotExist:
        return True

    return settings_profile.account_deletion_scheduled_for is None


def jwt_user_authentication_rule(user):
    return user_has_valid_account_status(user)


class AccountStatusJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not user_has_valid_account_status(user):
            raise exceptions.AuthenticationFailed(
                ACCOUNT_STATUS_MESSAGE,
                code="user_inactive",
            )
        return user


class AccountStatusSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        user = getattr(request._request, "user", None)
        if (
            user
            and getattr(user, "is_authenticated", False)
            and not user_has_valid_account_status(user)
        ):
            logout(request._request)
            raise exceptions.AuthenticationFailed(
                ACCOUNT_STATUS_MESSAGE,
                code="user_inactive",
            )

        return super().authenticate(request)

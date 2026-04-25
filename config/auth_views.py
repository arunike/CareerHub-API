from django.contrib.auth import authenticate, get_user_model, logout
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .user_ownership import claim_legacy_records_for_user, ensure_user_settings


def _serialize_user(user):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.get_full_name() or user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def _issue_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


def _authenticate_with_email(request, email, password):
    user_model = get_user_model()
    email_field = getattr(user_model, "EMAIL_FIELD", "email")
    user_by_email = user_model.objects.filter(**{f"{email_field}__iexact": email}).first()
    if user_by_email is None:
        return None

    username_field = user_model.USERNAME_FIELD
    return authenticate(
        request,
        password=password,
        **{username_field: getattr(user_by_email, username_field)},
    )


def _get_signup_status_payload():
    has_users = get_user_model()._default_manager.exists()
    can_signup = settings.ALLOW_PUBLIC_SIGNUP
    return {
        "can_signup": can_signup,
        "mode": "public" if can_signup else "disabled",
        "has_users": has_users,
        "email_only": True,
        "message": (
            "Create a new account with your email address."
            if can_signup
            else "Public signup is disabled for this deployment."
        ),
    }


def _split_full_name(full_name):
    normalized = " ".join(full_name.split())
    if not normalized:
        return "", ""
    if " " not in normalized:
        return normalized, ""
    first_name, last_name = normalized.split(" ", 1)
    return first_name, last_name


class AuthCsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "CSRF cookie set."}, status=status.HTTP_200_OK)


class AuthLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        email = (request.data.get("email") or request.data.get("identifier") or "").strip().lower()
        password = request.data.get("password") or ""

        if not email or not password:
            return Response(
                {"error": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = _authenticate_with_email(request, email, password)
        if user is None:
            return Response({"error": "Invalid email or password."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            return Response({"error": "This account is inactive."}, status=status.HTTP_403_FORBIDDEN)

        claim_legacy_records_for_user(user)
        ensure_user_settings(user)
        return Response(
            {
                "user": _serialize_user(user),
                **_issue_tokens_for_user(user),
            },
            status=status.HTTP_200_OK,
        )


class AuthSignupStatusView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(_get_signup_status_payload(), status=status.HTTP_200_OK)


class AuthSignupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    def post(self, request):
        signup_status = _get_signup_status_payload()
        if not signup_status["can_signup"]:
            return Response(
                {
                    "error": "Signup is disabled for this deployment.",
                    **signup_status,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user_model = get_user_model()
        email_field = getattr(user_model, "EMAIL_FIELD", "email")
        email = (request.data.get("email") or "").strip().lower()
        full_name = (request.data.get("full_name") or request.data.get("fullName") or "").strip()
        password = request.data.get("password") or ""
        confirm_password = request.data.get("confirm_password") or request.data.get("confirmPassword") or ""

        errors = {}

        if not full_name:
            errors["full_name"] = "Full name is required."

        if not email:
            errors["email"] = "Email is required."
        else:
            try:
                validate_email(email)
            except DjangoValidationError:
                errors["email"] = "Enter a valid email address."
            else:
                if user_model._default_manager.filter(**{f"{email_field}__iexact": email}).exists():
                    errors["email"] = "Email is already in use."

        if not password:
            errors["password"] = "Password is required."
        elif password != confirm_password:
            errors["confirm_password"] = "Passwords do not match."
        else:
            try:
                validate_password(password)
            except DjangoValidationError as exc:
                errors["password"] = " ".join(exc.messages)

        if errors:
            first_message = next(iter(errors.values()))
            return Response(
                {
                    "error": first_message,
                    "errors": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            create_user_kwargs = {
                user_model.USERNAME_FIELD: email,
                "password": password,
            }
            if email_field != user_model.USERNAME_FIELD:
                create_user_kwargs[email_field] = email
            user = user_model._default_manager.create_user(**create_user_kwargs)
            first_name, last_name = _split_full_name(full_name)
            if hasattr(user, "first_name"):
                user.first_name = first_name
            if hasattr(user, "last_name"):
                user.last_name = last_name
            user.save()

        ensure_user_settings(user)
        if settings.AUTO_LOGIN_AFTER_SIGNUP:
            claim_legacy_records_for_user(user)
            tokens = _issue_tokens_for_user(user)
            return Response(
                {
                    "user": _serialize_user(user),
                    "mode": "public",
                    "authenticated": True,
                    **tokens,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "mode": "public",
                "authenticated": False,
                "requires_login": True,
                "message": "Account created. Sign in to continue.",
            },
            status=status.HTTP_201_CREATED,
        )


class AuthLogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass

        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuthRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token_refresh"

    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class AuthMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": _serialize_user(request.user)}, status=status.HTTP_200_OK)

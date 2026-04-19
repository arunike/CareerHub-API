from django.urls import path

from .auth_views import AuthCsrfView, AuthLoginView, AuthLogoutView, AuthMeView, AuthSignupStatusView, AuthSignupView


urlpatterns = [
    path("csrf/", AuthCsrfView.as_view(), name="auth-csrf"),
    path("login/", AuthLoginView.as_view(), name="auth-login"),
    path("signup-status/", AuthSignupStatusView.as_view(), name="auth-signup-status"),
    path("signup/", AuthSignupView.as_view(), name="auth-signup"),
    path("logout/", AuthLogoutView.as_view(), name="auth-logout"),
    path("me/", AuthMeView.as_view(), name="auth-me"),
]

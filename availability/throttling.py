from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class PublicBookingSlotsThrottle(SimpleRateThrottle):
    scope = "public_booking_slots"
    rate = "20/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class PublicBookingCreateThrottle(SimpleRateThrottle):
    scope = "public_booking_create"
    rate = "5/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class AIProviderRelayThrottle(UserRateThrottle):
    scope = "ai_provider_relay"

import json
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from availability.models import UserSettings
from availability.ai_provider import relay_ai_provider_chat_completion

from ..models import Offer
from ..serializers import OfferSerializer
from ..services.offers import calculate_realizable_equity, ensure_offers_for_offer_status_applications


def _has_ai_provider_config(user_settings):
    return bool(
        getattr(user_settings, 'ai_provider_endpoint', '')
        and getattr(user_settings, 'ai_provider_model', '')
        and user_settings.has_ai_provider_api_key()
    )


def _clean_json_output(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.select_related('application__company').all()
    serializer_class = OfferSerializer

    def get_queryset(self):
        ensure_offers_for_offer_status_applications(self.request.user)
        return Offer.objects.select_related('application__company').filter(application__user=self.request.user)

    @action(detail=False, methods=['post'], url_path='transition-advisor')
    def transition_advisor(self, request):
        user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
        if not _has_ai_provider_config(user_settings):
            return Response(
                {"error": "AI Provider is not configured. Please go to Settings to configure your AI provider (Gemini or OpenAI)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        current_pain_points = request.data.get('current_pain_points', [])
        custom_pain_points = request.data.get('custom_pain_points', '')
        promotion_timeline = request.data.get('promotion_timeline', 'Unknown')
        include_job_hunting = request.data.get('include_job_hunting', False)
        simulated_offers = request.data.get('simulated_offers', [])

        offers = Offer.objects.select_related('application__company').filter(application__user=request.user)
        
        serialized_real_offers = []
        for o in offers:
            app = o.application
            realizable_equity = calculate_realizable_equity(
                o.equity,
                o.equity_liquidity,
                o.equity_buyback_value,
            )
            serialized_real_offers.append({
                "company_name": app.company.name,
                "role_title": app.role_title,
                "base_salary": float(o.base_salary),
                "bonus": float(o.bonus),
                "equity": float(realizable_equity),
                "granted_equity": float(o.equity),
                "equity_liquidity": o.equity_liquidity,
                "sign_on": float(o.sign_on),
                "benefits_value": float(o.benefits_value),
                "pto_days": o.pto_days,
                "is_unlimited_pto": o.is_unlimited_pto,
                "is_current": o.is_current,
                "rto_policy": app.rto_policy,
                "rto_days_per_week": app.rto_days_per_week,
                "commute_cost_value": float(app.commute_cost_value or 0),
                "commute_cost_frequency": app.commute_cost_frequency,
                "growth_score": app.growth_score,
                "work_life_score": app.work_life_score,
                "brand_score": app.brand_score,
                "team_score": app.team_score,
            })

        # Process simulated offers
        serialized_simulated_offers = []
        for o in simulated_offers:
            realizable_equity = calculate_realizable_equity(
                o.get('equity'),
                o.get('equity_liquidity'),
                o.get('equity_buyback_value'),
            )
            serialized_simulated_offers.append({
                "company_name": o.get('custom_company_name') or o.get('company_name') or 'Custom Scenario',
                "role_title": o.get('custom_role_title') or o.get('role_title') or 'Scenario Role',
                "base_salary": float(o.get('base_salary') or 0),
                "bonus": float(o.get('bonus') or 0),
                "equity": float(realizable_equity),
                "granted_equity": float(o.get('equity') or 0),
                "equity_liquidity": o.get('equity_liquidity') or 'LIQUID',
                "sign_on": float(o.get('sign_on') or 0),
                "benefits_value": float(o.get('benefits_value') or 0),
                "pto_days": int(o.get('pto_days') or 15),
                "is_unlimited_pto": bool(o.get('is_unlimited_pto') or False),
                "is_current": False,
                "rto_policy": o.get('rto_policy') or 'HYBRID',
                "rto_days_per_week": int(o.get('rto_days_per_week') or 3),
                "commute_cost_value": float(o.get('commute_cost_value') or 0),
                "commute_cost_frequency": o.get('commute_cost_frequency') or 'MONTHLY',
                "growth_score": o.get('growth_score'),
                "work_life_score": o.get('work_life_score'),
                "brand_score": o.get('brand_score'),
                "team_score": o.get('team_score'),
            })

        all_options = serialized_real_offers + serialized_simulated_offers
        current_job = next((o for o in all_options if o["is_current"]), None)
        other_offers = [o for o in all_options if not o["is_current"]]

        prompt_data = {
            "current_job": current_job,
            "pain_points": current_pain_points,
            "custom_pain_points": custom_pain_points,
            "promotion_timeline": promotion_timeline,
            "include_job_hunting_option": include_job_hunting,
            "offers_to_compare": other_offers
        }

        system_prompt = (
            "You are an expert Career Transition Advisor and Executive Recruiter. Your task is to evaluate the user's current job "
            "against their new job offers (both real and simulated scenarios) and decide whether they should 'stay' at their current job, "
            "'hop' to one of the new offers, or 'start hunting' for better opportunities.\n\n"
            "Evaluate the decision quantitatively (total compensation, benefits, retirement, PTO, commute costs, RTO policies) and "
            "qualitatively (stress, work-life balance, career growth, tech stack, brand value, team quality, and promotion timeline). "
            "You must also carefully read and address any custom pain points or situational details provided by the user under 'custom_pain_points' "
            "when formulating your advice and reasoning.\n\n"
            "You must return a raw JSON object matching this schema. Do not output markdown code blocks. Return only the JSON content:\n"
            "{\n"
            "  \"verdict\": \"stay\" | \"hop\" | \"hunt\",\n"
            "  \"verdict_label\": \"e.g., Hop to Google, Stay at Current Job, or Start Job Hunting\",\n"
            "  \"confidence\": \"High\" | \"Medium\" | \"Low\",\n"
            "  \"financial_analysis\": \"Detailed comparison of total compensation, equity, taxes, and growth potential. Use brief, bulleted points or short paragraphs separated by double newlines for scanning. Highlight key numbers and values with markdown bolding (e.g. **$170k**).\",\n"
            "  \"qualitative_analysis\": \"Qualitative comparison covering WLB, remote policies, brand value, stress, and cultural alignment. Use brief, bulleted points or short paragraphs separated by double newlines for scanning. Highlight key metrics and scores with markdown bolding.\",\n"
            "  \"reasoning_summary\": [\"Bullet point summarizing the core arguments for the decision\"],\n"
            "  \"pros_cons\": {\n"
            "    \"current_job\": {\n"
            "      \"pros\": [\"string\"],\n"
            "      \"cons\": [\"string\"]\n"
            "    },\n"
            "    \"recommendation\": {\n"
            "      \"name\": \"string\",\n"
            "      \"pros\": [\"string\"],\n"
            "      \"cons\": [\"string\"]\n"
            "    }\n"
            "  },\n"
            "  \"next_steps_criteria\": {\n"
            "    \"title\": \"What criteria / types of companies to look for in their search\",\n"
            "    \"items\": [\"string\"]\n"
            "  },\n"
            "  \"path_comparison\": {\n"
            "    \"scenario_a_label\": \"Label for Option A (e.g. Stay at TikTok / Accept Lumen Offer)\",\n"
            "    \"scenario_a_outcome\": \"Short, high-impact outcome analysis of Option A. Highlight key positive/negative metrics with markdown bolding.\",\n"
            "    \"scenario_b_label\": \"Label for Option B (e.g. Start Job Hunting)\",\n"
            "    \"scenario_b_outcome\": \"Short, high-impact outcome analysis of Option B. Highlight key positive/negative metrics with markdown bolding.\"\n"
            "  }\n"
            "}"
        )

        try:
            response = relay_ai_provider_chat_completion(
                user_settings=user_settings,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            raw_content = response['choices'][0]['message']['content']
            cleaned = _clean_json_output(raw_content)
            parsed_result = json.loads(cleaned)
            return Response(parsed_result)
        except Exception as e:
            return Response(
                {"error": f"AI evaluation failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

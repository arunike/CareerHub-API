from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .custom_widgets import process_query

class CustomWidgetQueryView(APIView):
    def post(self, request):
        query = request.data.get('query')
        context = request.data.get('context', 'availability')
        
        if not query:
            return Response({'error': 'Query is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        result = process_query(query, context)
        
        if 'error' in result:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
            
        return Response(result)

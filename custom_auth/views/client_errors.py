from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
import logging

# Dedicated logger name so the observability stack can filter these lines:
# Loki query {container="..."} |= "client_error"
logger = logging.getLogger('client_errors')


class ClientErrorThrottle(ScopedRateThrottle):
    scope = 'client_errors'


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([ClientErrorThrottle])
def report_client_error(request):
    """
    Beacon target for the frontend AppErrorBoundary: React render crashes
    land here and become log lines the observability stack can see.
    AllowAny — a crash on the login page must be reportable too.
    Nothing is stored; the log pipeline is the sink.
    """
    message = str(request.data.get('message', ''))[:500]
    stack = str(request.data.get('stack', ''))[:4000]
    component_stack = str(request.data.get('component_stack', ''))[:4000]
    url = str(request.data.get('url', ''))[:500]

    logger.error(
        'client_error url=%s message=%s stack=%s component_stack=%s',
        url, message, stack, component_stack,
    )
    return Response({'status': 'logged'}, status=status.HTTP_202_ACCEPTED)

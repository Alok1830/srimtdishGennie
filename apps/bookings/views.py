"""
Views for bookings app.
"""
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework import generics, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Booking
from .serializers import BookingSerializer, BookingCreateSerializer
from apps.accounts.permissions import IsCustomer, IsMaid, IsAdmin
from apps.notifications.models import Notification


def _notify(user, title, message, notif_type='booking', action_url=''):
    if user:
        Notification.objects.create(
            user=user,
            title=title,
            message=message,
            notif_type=notif_type,
            action_url=action_url,
        )


class BookingListCreateView(generics.ListCreateAPIView):
    """List own bookings or create a new booking (customer)."""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BookingCreateSerializer
        return BookingSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_admin_user:
            return Booking.objects.all()
        if user.is_customer_user:
            return Booking.objects.filter(customer=user)
        elif user.is_maid_user:
            return Booking.objects.filter(maid=user)
        return Booking.objects.none()

    def create(self, request, *args, **kwargs):
        if not request.user.is_customer_user or request.user.is_admin_user:
            raise PermissionDenied('Only customers can create bookings.')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save(customer=request.user)

        if booking.maid_id and booking.status == Booking.Status.PENDING:
            booking.status = Booking.Status.ACCEPTED
            booking.accepted_at = timezone.now()
            booking.save(update_fields=['status', 'accepted_at'])
            _notify(
                booking.maid,
                'New booking assigned',
                f'Booking #{booking.pk} has been assigned to you.',
                action_url=f'/maid-panel/navigation/?booking_id={booking.pk}',
            )
            _notify(
                booking.customer,
                'Booking confirmed',
                f'Your booking #{booking.pk} has been accepted.',
                action_url=f'/live-tracking/{booking.pk}/',
            )
        else:
            _notify(
                booking.customer,
                'Booking created',
                f'Your booking #{booking.pk} is waiting for a maid.',
                action_url=f'/my-bookings/',
            )

        # Return full serializer with computed fields (maid_name, service_name, etc.)
        response_serializer = BookingSerializer(booking)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class BookingDetailView(generics.RetrieveUpdateAPIView):
    """Booking detail and update."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin_user:
            return Booking.objects.all()
        return Booking.objects.filter(
            customer=user
        ) | Booking.objects.filter(maid=user)


class AcceptBookingView(views.APIView):
    """Maid accepts a booking."""
    permission_classes = [IsAuthenticated, IsMaid]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, status='pending')
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found or already accepted.'}, status=404)
        booking.maid = request.user
        booking.status = 'accepted'
        booking.accepted_at = timezone.now()
        booking.save()
        _notify(
            booking.customer,
            'Booking accepted',
            f'{request.user.get_full_name() or request.user.username} accepted booking #{booking.pk}.',
            action_url=f'/live-tracking/{booking.pk}/',
        )
        return Response({'message': 'Booking accepted!', 'booking': BookingSerializer(booking).data})


class RejectBookingView(views.APIView):
    """Maid rejects a booking."""
    permission_classes = [IsAuthenticated, IsMaid]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, maid=request.user)
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found.'}, status=404)
        booking.status = 'pending'
        booking.maid = None
        booking.save()
        return Response({'message': 'Booking rejected.'})


class EnRouteBookingView(views.APIView):
    """Maid marks an accepted booking as en route."""
    permission_classes = [IsAuthenticated, IsMaid]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, maid=request.user, status='accepted')
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found or cannot be marked en route.'}, status=404)
        booking.status = 'en_route'
        booking.save(update_fields=['status'])
        _notify(
            booking.customer,
            'Maid is en route',
            f'Your maid is on the way for booking #{booking.pk}.',
            action_url=f'/live-tracking/{booking.pk}/',
        )
        return Response({'message': 'Maid is en route.', 'booking': BookingSerializer(booking).data})


class StartBookingView(views.APIView):
    """Maid starts service (OTP verification)."""
    permission_classes = [IsAuthenticated, IsMaid]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, maid=request.user, status__in=['accepted', 'en_route'])
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found.'}, status=404)

        otp = request.data.get('otp', '')
        if otp != booking.otp:
            return Response({'error': 'Invalid OTP.'}, status=400)

        booking.status = 'in_progress'
        booking.started_at = timezone.now()
        booking.save()
        _notify(
            booking.customer,
            'Service started',
            f'Booking #{booking.pk} has started.',
            action_url=f'/live-tracking/{booking.pk}/',
        )
        return Response({'message': 'Service started!'})


class CompleteBookingView(views.APIView):
    """Maid completes service."""
    permission_classes = [IsAuthenticated, IsMaid]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, maid=request.user, status='in_progress')
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found.'}, status=404)
        booking.status = 'completed'
        booking.completed_at = timezone.now()
        booking.save()
        _notify(
            booking.customer,
            'Service completed',
            f'Booking #{booking.pk} is complete.',
            action_url=f'/my-bookings/',
        )

        # Update maid stats
        if hasattr(request.user, 'maid_profile'):
            profile = request.user.maid_profile
            profile.total_jobs += 1
            profile.total_earnings += booking.final_amount
            profile.save()

        return Response({'message': 'Service completed!', 'booking': BookingSerializer(booking).data})


class CancelBookingView(views.APIView):
    """Customer cancels a booking."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, customer=request.user, status__in=['pending', 'accepted'])
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found or cannot be cancelled.'}, status=404)
        booking.status = 'cancelled'
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = request.data.get('reason', '')
        booking.save()
        _notify(
            booking.customer,
            'Booking cancelled',
            f'Booking #{booking.pk} has been cancelled.',
            action_url=f'/my-bookings/',
        )
        _notify(
            booking.maid,
            'Booking cancelled',
            f'Booking #{booking.pk} was cancelled by the customer.',
            action_url=f'/maid-panel/jobs/',
        )
        return Response({'message': 'Booking cancelled.'})


class MaidPendingRequestsView(generics.ListAPIView):
    """List pending bookings for maids to accept."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated, IsMaid]

    def get_queryset(self):
        return Booking.objects.filter(status='pending').order_by('-created_at')


class MaidActiveJobsView(generics.ListAPIView):
    """List active jobs for a maid."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated, IsMaid]

    def get_queryset(self):
        return Booking.objects.filter(
            maid=self.request.user,
            status__in=['accepted', 'en_route', 'in_progress']
        )

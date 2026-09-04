# JEEVAN — Flutter integration (for the real app repo)

The backend above is the reference implementation of the JEEVAN API. The Flutter app
consumes exactly these endpoints. Drop-in code for the existing architecture
(Riverpod + GoRouter + Dio):

## 1. Dio client with JWT refresh (`lib/core/network/api_client.dart`)

```dart
class ApiClient {
  final Dio _dio = Dio(BaseOptions(baseUrl: 'https://<host>/api/v1'));

  ApiClient(this._tokens) {
    _dio.interceptors.addAll([
      InterceptorsWrapper(
        onRequest: (o, h) async {
          o.headers['Authorization'] = 'Bearer ${await _tokens.access()}';
          h.next();
        },
        onError: (e, h) async {
          if (e.response?.statusCode == 401 && await _tokens.refresh()) {
            final retry = await _dio.fetch(e.requestOptions
              ..headers['Authorization'] = 'Bearer ${await _tokens.access()}');
            return h.resolve(retry);
          }
          h.next();
        },
      ),
    ]);
  }
  final TokenRepository _tokens;
}
```

## 2. Riverpod auth controller (`lib/features/auth/auth_controller.dart`)

```dart
class AuthState { final User? user; final List<String> permissions; final bool loading; }
final authControllerProvider =
    AsyncNotifierProvider<AuthController, AuthState>(AuthController.new);

class AuthController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async => _restore();        // GET /auth/me

  Future<void> login(String identifier, String password, bool remember) async {
    final res = await api.post('/auth/login', data: {
      'identifier': identifier, 'password': password, 'remember': remember});
    await tokens.save(res.data['access_token'], res.data['refresh_token'], remember);
    state = AsyncData(AuthState(
        user: User.fromJson(res.data['user']),
        permissions: List<String>.from(res.data['permissions']),
        loading: false));
    // role redirect — backend also enforces this on every API call
    go(_dashboardFor(res.data['user']['role']));
  }
}

String _dashboardFor(String role) => switch (role) {
  'citizen' => '/citizen',
  'ambulance_driver' => '/ambulance',
  'hospital_staff' => '/hospital',
  'police_officer' => '/police',
  'administrator' => '/admin',
  _ => '/',
};
```

## 3. GoRouter with auth + role guards (`lib/app/router.dart`)

```dart
final router = GoRouter(
  redirect: (context, state) async {
    final auth = ref.read(authControllerProvider).valueOrNull;
    final loggingIn = state.matchedLocation == '/login';
    if (auth?.user == null) return loggingIn ? null : '/login';

    const guards = {
      '/citizen': 'citizen', '/ambulance': 'ambulance_driver',
      '/hospital': 'hospital_staff', '/police': 'police_officer',
      '/admin': 'administrator',
    };
    final required = guards.entries
        .firstWhere((e) => state.matchedLocation.startsWith(e.key),
            orElse: () => const MapEntry('', '')).value;
    if (required.isNotEmpty && auth!.user!.role != required) {
      return _dashboardFor(auth.user!.role);   // block cross-role URLs
    }
    return loggingIn ? _dashboardFor(auth!.user!.role) : null;
  },
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
    GoRoute(path: '/citizen', builder: (_, __) => const CitizenDashboard(), routes: [
      GoRoute(path: 'sos', builder: (_, __) => const SosPage()),
      GoRoute(path: 'history', builder: (_, __) => const HistoryPage()),
      GoRoute(path: 'profile', builder: (_, __) => const ProfilePage()),
    ]),
    GoRoute(path: '/ambulance', builder: (_, __) => const AmbulanceDashboard()),
    GoRoute(path: '/hospital', builder: (_, __) => const HospitalDashboard()),
    GoRoute(path: '/police', builder: (_, __) => const PoliceDashboard()),
    GoRoute(path: '/admin', builder: (_, __) => const AdminDashboard(), routes: [
      GoRoute(path: 'cctv', builder: (_, __) => const CctvUploadPage()),
      /* users / units / analytics / reports */
    ]),
  ],
);
```

## 4. CCTV upload (`lib/features/cctv/cctv_upload_page.dart`)

```dart
final form = FormData.fromMap({
  'file': await MultipartFile.fromFile(path, filename: name),
  'camera_id': cameraId, 'latitude': lat, 'longitude': lng,
});
final progress = StreamController<double>();
await api.dio.post('/cctv/upload', data: form,
  onSendProgress: (sent, total) => progress.add(sent / total));
// then GET /cctv/{id} or listen on the WebSocket for status/result
```

## 5. WebSocket live updates

Connect to `ws(s)://<host>/ws?token=<access>`; event types:
`emergency_created`, `sos_created`, `cctv_status`, `cctv_result`,
`mission_state`, `hospital_prep`, `case_closed`. Reconnect with backoff;
re-authenticate after token refresh.

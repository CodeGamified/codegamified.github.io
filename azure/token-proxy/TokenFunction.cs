using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Http;
using Microsoft.Extensions.Logging;

namespace CodeGamifiedTokenProxy;

/// <summary>
/// GitHub OAuth token exchange proxy for CodeGamified.
/// POST /api/auth/token — exchanges a GitHub OAuth code for an access_token.
///
/// Security:
///   - Strict CORS: origin allowlist from ALLOWED_ORIGINS env var
///   - Input validation: code must be exactly 20 hex chars (GitHub format)
///   - Request size limit: rejects bodies > 1 KB
///   - Content-Type enforcement: must be application/json
///   - Response sanitization: only returns access_token, never reflects input
///   - Security headers: X-Content-Type-Options, X-Frame-Options, etc.
///   - Timeout: 10s HttpClient to GitHub (prevents hanging connections)
///   - Error responses: generic messages, no internal detail leakage
/// </summary>
public class TokenFunction
{
    // ── Constants ────────────────────────────────────────────
    private const string GitHubTokenUrl = "https://github.com/login/oauth/access_token";
    private const int MaxBodyBytes = 1024; // 1 KB
    private static readonly Regex GitHubCodeRegex = new(@"^[0-9a-f]{20}$", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly TimeSpan FetchTimeout = TimeSpan.FromSeconds(10);

    // ── Shared HttpClient (best practice: reuse across invocations) ──
    private static readonly HttpClient GitHubClient = new()
    {
        Timeout = FetchTimeout,
        DefaultRequestHeaders =
        {
            { "User-Agent", "CodeGamified-token-proxy/1.0" },
            { "Accept", "application/json" },
        },
    };

    private readonly ILogger<TokenFunction> _logger;

    public TokenFunction(ILogger<TokenFunction> logger)
    {
        _logger = logger;
    }

    // ── Security headers applied to every response ──────────
    private static void ApplySecurityHeaders(HttpResponseData response)
    {
        response.Headers.Add("X-Content-Type-Options", "nosniff");
        response.Headers.Add("X-Frame-Options", "DENY");
        response.Headers.Add("X-XSS-Protection", "0");
        response.Headers.Add("Referrer-Policy", "no-referrer");
        response.Headers.Add("Cache-Control", "no-store, no-cache, must-revalidate");
        response.Headers.Add("Pragma", "no-cache");
    }

    // ── Origin allowlist ────────────────────────────────────
    private static HashSet<string> GetAllowedOrigins()
    {
        var raw = Environment.GetEnvironmentVariable("ALLOWED_ORIGINS") ?? "";
        return raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                  .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static bool IsAllowedOrigin(string? origin)
    {
        if (string.IsNullOrEmpty(origin)) return false;
        return GetAllowedOrigins().Contains(origin);
    }

    // ── Response helpers ────────────────────────────────────
    private static void ApplyCorsHeaders(HttpResponseData response, string? origin)
    {
        ApplySecurityHeaders(response);
        if (!string.IsNullOrEmpty(origin) && IsAllowedOrigin(origin))
        {
            response.Headers.Add("Access-Control-Allow-Origin", origin);
            response.Headers.Add("Vary", "Origin");
        }
    }

    private static HttpResponseData ErrorResponse(HttpRequestData req, HttpStatusCode status, string message, string? origin)
    {
        var response = req.CreateResponse(status);
        ApplyCorsHeaders(response, origin);
        response.Headers.Add("Content-Type", "application/json");
        response.WriteString(JsonSerializer.Serialize(new { error = message }));
        return response;
    }

    private static HttpResponseData SuccessResponse(HttpRequestData req, object body, string? origin)
    {
        var response = req.CreateResponse(HttpStatusCode.OK);
        ApplyCorsHeaders(response, origin);
        response.Headers.Add("Content-Type", "application/json");
        response.WriteString(JsonSerializer.Serialize(body));
        return response;
    }

    // ── Main handler ────────────────────────────────────────
    [Function("token")]
    public async Task<HttpResponseData> Run(
        [HttpTrigger(AuthorizationLevel.Anonymous, "post", "options", Route = "auth/token")]
        HttpRequestData req)
    {
        var origin = req.Headers.TryGetValues("Origin", out var originValues)
            ? originValues.FirstOrDefault() ?? ""
            : "";

        // ── Preflight ──────────────────────────────────
        if (req.Method.Equals("OPTIONS", StringComparison.OrdinalIgnoreCase))
        {
            if (!IsAllowedOrigin(origin))
            {
                _logger.LogWarning("[CORS] Rejected preflight from origin: {Origin}", origin);
                var forbidden = req.CreateResponse(HttpStatusCode.Forbidden);
                ApplySecurityHeaders(forbidden);
                return forbidden;
            }
            var preflight = req.CreateResponse(HttpStatusCode.NoContent);
            ApplyCorsHeaders(preflight, origin);
            preflight.Headers.Add("Access-Control-Allow-Methods", "POST, OPTIONS");
            preflight.Headers.Add("Access-Control-Allow-Headers", "Content-Type");
            preflight.Headers.Add("Access-Control-Max-Age", "86400");
            return preflight;
        }

        // ── CORS origin check (non-preflight) ──────────
        if (!IsAllowedOrigin(origin))
        {
            _logger.LogWarning("[CORS] Rejected POST from origin: {Origin}", origin);
            return ErrorResponse(req, HttpStatusCode.Forbidden, "Origin not allowed", null);
        }

        // ── Content-Type enforcement ───────────────────
        var contentType = req.Headers.TryGetValues("Content-Type", out var ctValues)
            ? ctValues.FirstOrDefault() ?? ""
            : "";
        if (!contentType.Contains("application/json", StringComparison.OrdinalIgnoreCase))
        {
            return ErrorResponse(req, HttpStatusCode.UnsupportedMediaType,
                "Content-Type must be application/json", origin);
        }

        // ── Request size limit (Content-Length header) ─
        if (req.Headers.TryGetValues("Content-Length", out var clValues))
        {
            if (long.TryParse(clValues.FirstOrDefault(), out var cl) && cl > MaxBodyBytes)
            {
                return ErrorResponse(req, HttpStatusCode.RequestEntityTooLarge,
                    "Request too large", origin);
            }
        }

        // ── Parse body ─────────────────────────────────
        string rawBody;
        try
        {
            using var reader = new StreamReader(req.Body, Encoding.UTF8);
            rawBody = await reader.ReadToEndAsync();
        }
        catch
        {
            return ErrorResponse(req, HttpStatusCode.BadRequest, "Invalid request body", origin);
        }

        if (rawBody.Length > MaxBodyBytes)
        {
            return ErrorResponse(req, HttpStatusCode.RequestEntityTooLarge,
                "Request too large", origin);
        }

        JsonElement json;
        try
        {
            json = JsonSerializer.Deserialize<JsonElement>(rawBody);
        }
        catch
        {
            return ErrorResponse(req, HttpStatusCode.BadRequest, "Invalid JSON", origin);
        }

        // ── Validate code format ───────────────────────
        if (!json.TryGetProperty("code", out var codeProp) ||
            codeProp.ValueKind != JsonValueKind.String)
        {
            return ErrorResponse(req, HttpStatusCode.BadRequest,
                "Invalid code format: expected 20 hex characters", origin);
        }

        var code = codeProp.GetString()!;
        if (!GitHubCodeRegex.IsMatch(code))
        {
            return ErrorResponse(req, HttpStatusCode.BadRequest,
                "Invalid code format: expected 20 hex characters", origin);
        }

        // ── Validate env config ────────────────────────
        var clientId = Environment.GetEnvironmentVariable("OAUTH_CLIENT_ID");
        var clientSecret = Environment.GetEnvironmentVariable("OAUTH_CLIENT_SECRET");
        if (string.IsNullOrEmpty(clientId) || string.IsNullOrEmpty(clientSecret))
        {
            _logger.LogError("[config] OAUTH_CLIENT_ID or OAUTH_CLIENT_SECRET not set");
            return ErrorResponse(req, HttpStatusCode.InternalServerError,
                "Server misconfigured", origin);
        }

        // ── Exchange code with GitHub ──────────────────
        try
        {
            var payload = JsonSerializer.Serialize(new
            {
                client_id = clientId,
                client_secret = clientSecret,
                code,
            });
            var content = new StringContent(payload, Encoding.UTF8, "application/json");

            var ghResponse = await GitHubClient.PostAsync(GitHubTokenUrl, content);

            if (!ghResponse.IsSuccessStatusCode)
            {
                _logger.LogWarning("[github] Token exchange HTTP {Status}", (int)ghResponse.StatusCode);
                return ErrorResponse(req, HttpStatusCode.BadGateway,
                    "GitHub token exchange failed", origin);
            }

            var ghBody = await ghResponse.Content.ReadAsStringAsync();
            var ghData = JsonSerializer.Deserialize<JsonElement>(ghBody);

            // GitHub returns error in the JSON body, not via HTTP status
            if (ghData.TryGetProperty("error", out var errorProp))
            {
                var errorDesc = ghData.TryGetProperty("error_description", out var descProp)
                    ? descProp.GetString() : "";
                _logger.LogWarning("[github] {Error}: {Description}", errorProp.GetString(), errorDesc);
                return ErrorResponse(req, HttpStatusCode.BadRequest,
                    "GitHub rejected the code", origin);
            }

            if (!ghData.TryGetProperty("access_token", out var tokenProp) ||
                tokenProp.ValueKind != JsonValueKind.String)
            {
                _logger.LogError("[github] No access_token in response");
                return ErrorResponse(req, HttpStatusCode.BadGateway,
                    "No token received from GitHub", origin);
            }

            // ── Return ONLY the access_token — never reflect code, scope, etc. ──
            return SuccessResponse(req, new { access_token = tokenProp.GetString() }, origin);
        }
        catch (TaskCanceledException)
        {
            _logger.LogError("[github] Token exchange timed out");
            return ErrorResponse(req, HttpStatusCode.GatewayTimeout,
                "GitHub request timed out", origin);
        }
        catch (Exception ex)
        {
            _logger.LogError("[github] Token exchange error: {Message}", ex.Message);
            return ErrorResponse(req, HttpStatusCode.BadGateway,
                "Token exchange failed", origin);
        }
    }
}

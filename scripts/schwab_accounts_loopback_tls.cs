// Windows SslStream keeps the certificate's nonexportable private key in CNG.
// Only three GET routes are bridged, only over IPv4 loopback, without URL logs.
using System;
using System.IO;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

public static class JJSchwabAccountsLoopbackTls {
    public static string LastFailureStage = null;
    public static int LastFailureCode = 0;
    public static string NormalizeRequest(string text) {
        if (text.Length > 16384 || !text.EndsWith("\r\n\r\n"))
            throw new InvalidDataException("REQUEST_REJECTED");
        string[] lines = text.Split(new string[] {"\r\n"}, StringSplitOptions.None);
        string[] first = lines[0].Split(' ');
        if (first.Length != 3 || first[0] != "GET" || first[2] != "HTTP/1.1" ||
            first[1].Length > 8192 || !Regex.IsMatch(first[1],
            @"\A/schwab/(health|start|callback)(\?[^\s#]*)?\z"))
            throw new InvalidDataException("REQUEST_REJECTED");
        int hosts = 0, cookies = 0;
        string cookie = null;
        for (int i = 1; i < lines.Length - 2; i++) {
            int colon = lines[i].IndexOf(':');
            if (colon < 1 || !Regex.IsMatch(lines[i].Substring(0, colon), @"\A[A-Za-z0-9-]+\z"))
                throw new InvalidDataException("REQUEST_REJECTED");
            string name = lines[i].Substring(0, colon).ToLowerInvariant();
            string value = lines[i].Substring(colon + 1).Trim();
            if (value.IndexOfAny(new char[] {'\r', '\n', '\0'}) >= 0)
                throw new InvalidDataException("REQUEST_REJECTED");
            if (name == "host") {
                hosts++;
                if (value != "127.0.0.1:8186") throw new InvalidDataException("REQUEST_REJECTED");
            }
            if (name == "content-length" || name == "transfer-encoding" || name == "expect")
                throw new InvalidDataException("REQUEST_REJECTED");
            if (name == "cookie") {
                cookies++;
                if (cookies > 1 || value.Length > 4096) throw new InvalidDataException("REQUEST_REJECTED");
                cookie = value;
            }
        }
        if (hosts != 1) throw new InvalidDataException("REQUEST_REJECTED");
        return "GET " + first[1] + " HTTP/1.0\r\nHost: 127.0.0.1:8186\r\n" +
            (cookie == null ? "" : "Cookie: " + cookie + "\r\n") + "Connection: close\r\n\r\n";
    }

    static void Reply(Stream stream, int status) {
        byte[] response = Encoding.ASCII.GetBytes("HTTP/1.1 " + status + " Request unavailable\r\n" +
            "Content-Length: 0\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n");
        stream.Write(response, 0, response.Length);
    }

    static void Handle(TcpClient client, X509Certificate2 cert) {
        using (client) {
            if (!((IPEndPoint)client.Client.RemoteEndPoint).Address.Equals(IPAddress.Loopback)) return;
            client.ReceiveTimeout = 5000; client.SendTimeout = 5000;
            using (SslStream secure = new SslStream(client.GetStream(), false)) {
                secure.ReadTimeout = 5000; secure.WriteTimeout = 5000;
                string stage = "tls";
                try {
                    secure.AuthenticateAsServer(cert, false, SslProtocols.Tls12, false);
                    stage = "headers";
                    using (MemoryStream header = new MemoryStream()) {
                        int value;
                        while (header.Length < 16384 && (value = secure.ReadByte()) >= 0) {
                            if (value > 127 || value == 0) { Reply(secure, 400); return; }
                            header.WriteByte((byte)value);
                            byte[] bytes = header.GetBuffer(); int size = (int)header.Length;
                            if (size >= 4 && bytes[size-4] == 13 && bytes[size-3] == 10 &&
                                bytes[size-2] == 13 && bytes[size-1] == 10) break;
                        }
                        string forward;
                        try { forward = NormalizeRequest(Encoding.ASCII.GetString(header.ToArray())); }
                        catch (InvalidDataException) { Reply(secure, 400); return; }
                        // Never follow a redirect: Location and Secure cookie pass to browser unchanged.
                        stage = "backend";
                        using (TcpClient backend = new TcpClient()) {
                            backend.ReceiveTimeout = 35000; backend.SendTimeout = 5000;
                            backend.Connect(IPAddress.Loopback, 8187);
                            using (NetworkStream plain = backend.GetStream()) {
                                byte[] request = Encoding.ASCII.GetBytes(forward);
                                plain.Write(request, 0, request.Length);
                                using (MemoryStream response = new MemoryStream()) {
                                    byte[] buffer = new byte[4096]; int count;
                                    while ((count = plain.Read(buffer, 0, buffer.Length)) > 0) {
                                        response.Write(buffer, 0, count);
                                        if (response.Length > 32768) { Reply(secure, 502); return; }
                                    }
                                    byte[] payload = response.ToArray();
                                    secure.Write(payload, 0, payload.Length);
                                }
                            }
                        }
                    }
                } catch (Exception error) {
                    // Fixed stage + numeric code only, never exception text or request details.
                    LastFailureStage = stage; LastFailureCode = error.HResult;
                }
            }
        }
    }

    public static void Run(X509Certificate2 cert, string stopFile, int seconds) {
        TcpListener listener = new TcpListener(IPAddress.Loopback, 8186);
        DateTime end = DateTime.UtcNow.AddSeconds(seconds);
        try {
            listener.Start(8);
            while (DateTime.UtcNow < end && !File.Exists(stopFile)) {
                if (listener.Pending()) Handle(listener.AcceptTcpClient(), cert);
                else Thread.Sleep(100);
            }
        } finally { listener.Stop(); }
    }
}

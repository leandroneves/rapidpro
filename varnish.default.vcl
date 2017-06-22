vcl 4.0;

backend default {
    .host = "127.0.0.1";
    .port = "8000";
}

#sub vcl_recv {
#    # Happens before we check if we have this in cache already.
#    #
#    # Typically you clean up the request here, removing cookies you don't need,
#    # rewriting the request, etc.
#
#    if ( (req.http.host ~ "^(?i)connect.ilhasoft.mobi") && req.http.X-Forwarded-Proto !~ "(?i)https") {
#        set req.http.x-redir = "https://" + req.http.host + req.url;
#        return (synth(750, ""));
#    }
#    return (hash);
#}

sub vcl_backend_response {
}

sub vcl_deliver {
    if (req.url ~ "/") {
        set resp.http.Access-Control-Allow-Origin = "*";
        set resp.http.Access-Control-Allow-Methods = "GET, OPTIONS";
        set resp.http.Access-Control-Allow-Headers = "Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token";
    }
}

sub vcl_synth {
    if (resp.status == 750) {
        set resp.status = 301;
        set resp.http.Location = req.http.x-redir;
        return(deliver);
    }
}
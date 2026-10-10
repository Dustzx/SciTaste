// Keep the native receiver's versioned contracts, with FastResearch's page token.
(() => {
  const originalFetch = window.fetch.bind(window);
  let token;
  async function csrf() {
    if (!token) {
      const response = await originalFetch('/api/experiments/status', {credentials:'same-origin'});
      if (!response.ok) throw new Error('研究服务暂时不可用');
      token = (await response.json()).csrf_token;
    }
    return token;
  }
  window.fetch = async (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : input, location.href);
    const method = (init.method || request?.method || 'GET').toUpperCase();
    if (url.origin === location.origin && /^\/api\/v[1-4]\//.test(url.pathname) && !['GET','HEAD'].includes(method)) {
      const headers = new Headers(init.headers || request?.headers);
      headers.set('X-FastResearch-CSRF', await csrf());
      init = {...init, headers};
    }
    return originalFetch(input, init);
  };
})();

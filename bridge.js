/* In-page steampy API bridge.
 * Executed via the driver's `eval` command with a JSON arg:
 *   { "action": "...", ... }
 * Returns plain JSON-serialisable data. All requests run inside the logged-in
 * page so cookies AND the required `accessToken` header come along.
 */
async (arg) => {
  const A = typeof arg === 'string' ? JSON.parse(arg.replace(/^\uFEFF/, '')) : (arg || {});
  const tok = localStorage.getItem('accessToken') || '';

  const call = (method, url, body) => new Promise((res) => {
    const x = new XMLHttpRequest();
    x.open(method, url, true);
    x.timeout = A.timeout || 60000;
    x.setRequestHeader('Accept', 'application/json, text/plain, */*');
    x.setRequestHeader('accessToken', tok);
    if (body) x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8');
    x.onload = () => {
      try { res({ status: x.status, json: JSON.parse(x.responseText) }); }
      catch (e) { res({ status: x.status, err: 'parse', raw: String(x.responseText).slice(0, 400) }); }
    };
    x.onerror = () => res({ err: 'xhr_error' });
    x.ontimeout = () => res({ err: 'timeout' });
    x.send(body || null);
  });

  const compact = (g) => ({
    id: g.id, en: g.gameName, cn: g.gameNameCn, app: g.appId,
    url: g.gameUrl, type: g.steamApp ? g.steamApp.type : null,
    ori: g.oriPrice, tx: g.keyTxAmt, lp: g.keyPrice, ave: g.keyAveAmt,
    sales: g.keySales, salesCount: g.keySales
  });

  switch (A.action) {
    case 'token':
      return { token: tok ? tok.slice(0, 6) + '...' : null, hasToken: !!tok, url: location.href };

    case 'whoami': {
      let u = null;
      try { u = JSON.parse(localStorage.getItem('userInfo') || 'null'); } catch (e) {}
      return {
        id: u && u.id, name: u && u.userName, nick: u && u.nickName,
        hasToken: !!tok, token6: tok ? tok.slice(0, 6) : null, path: location.pathname
      };
    }

    case 'loginState': {
      let hasUser = false;
      try { hasUser = !!localStorage.getItem('userInfo'); } catch (e) {}
      return {
        url: location.href, path: location.pathname,
        hasToken: !!tok, hasUser: hasUser,
        loggedIn: !!tok && location.pathname !== '/login'
      };
    }

    case 'search': {
      const size = A.size || 10;
      const j = await call('GET', '/xboot/steamGame/saleKeyByName?pageNumber=1&pageSize=' + size +
        '&sort=id&order=asc&gameUrl=&gameName=' + encodeURIComponent(A.q || ''));
      const list = (j.json && j.json.result && j.json.result.content) || [];
      return { q: A.q, total: (j.json && j.json.result && j.json.result.totalElements) || 0, items: list.map(compact), err: j.err };
    }

    case 'getone': {
      const out = [];
      for (const id of (A.ids || [])) {
        const j = await call('GET', '/xboot/steamGame/getOne?gameId=' + encodeURIComponent(id));
        const g = (j.json && j.json.result) || {};
        out.push(compact(g));
        await new Promise(r => setTimeout(r, 150));
      }
      return { items: out };
    }

    case 'listself': {
      const size = A.size || 50;
      const maxPages = A.pages || 10;
      const rows = [];
      let total = null;
      for (let p = 1; p <= maxPages; p++) {
        const j = await call('GET', '/xboot/steamKeySale/listSelf?pageNumber=' + p + '&pageSize=' + size +
          '&sort=saleStatus&order=desc&gameId=');
        const c = (j.json && j.json.result && j.json.result.content) || [];
        if (total === null) total = (j.json && j.json.result && j.json.result.totalElements) || 0;
        for (const x of c) {
          rows.push({
            id: x.id, time: x.createTime, gameId: x.gameId,
            stock: x.stock, sold: x.sold, status: x.saleStatus,
            price: x.keyPrice, dumpStock: x.dumpStock
          });
        }
        if (rows.length >= total || !c.length) break;
        await new Promise(r => setTimeout(r, 150));
      }
      return { total, count: rows.length, rows };
    }

    case 'startsell': {
      const body = 'gameId=' + encodeURIComponent(A.gameId) +
        '&keys=' + encodeURIComponent(A.key) +
        '&keyWord=&sellPrice=' + encodeURIComponent(A.price) +
        '&syncUs=' + (A.syncUs ? 1 : 0) + '&osflag=0';
      const j = await call('POST', '/xboot/steamKeySale/startSell', body);
      const js = j.json || {};
      return {
        httpStatus: j.status,
        success: !!js.success,
        message: js.message || j.err || '',
        saleId: (js.result && js.result.id) || null,
        priceUsed: A.price,
        sentBody: body
      };
    }

    default:
      return { err: 'unknown action ' + A.action };
  }
}

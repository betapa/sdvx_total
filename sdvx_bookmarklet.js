const CONFIG = {
    owner: 'betapa', // 사용자에 맞게 수정
    repo: 'sdvx_total', // 사용자에 맞게 수정
    path: 'sdvx_playdata.csv' // 사용자에 맞게 수정
};

(async function() {
    // 0. 토큰 확인
    let token = localStorage.getItem('GH_TOKEN');
    if (!token) {
        token = prompt("GitHub Personal Access Token을 입력해주세요.\n(repo 권한 필요)");
        if (!token) return alert("토큰이 없어 취소합니다.");
        localStorage.setItem('GH_TOKEN', token);
    }

    const UI = {
        log: (msg) => console.log(`[SDVX] ${msg}`),
        error: (msg) => console.error(`[SDVX Error] ${msg}`),
        alert: (msg) => alert(`[SDVX Helper]\n${msg}`)
    };

    const randomSleep = (min, max) => {
        const ms = Math.floor(Math.random() * (max - min + 1) + min);
        return new Promise(resolve => setTimeout(resolve, ms));
    };

    try {
        UI.log("데이터 수집을 시작합니다...");

        const limit = 150; 
        const baseUrl = "https://p.eagate.573.jp/game/sdvx/vii/playdata/musicdata/index.html";

        const fetchOptions = {
            method: 'GET',
            credentials: 'include',
        };

        // 1. 첫 페이지 로드 및 전체 페이지 수 확인
        const firstPageUrl = `${baseUrl}?limit=${limit}&sort=0&page=1&_t=${Date.now()}`;
        const firstPageRes = await fetch(firstPageUrl, fetchOptions);
        const firstPageText = await firstPageRes.text();
        
        if (firstPageText.includes("login_form") || firstPageText.includes("ea_common_login")) {
            UI.error("세션이 만료되었거나 로그인이 풀려있습니다. e-amusement에 다시 로그인해주세요.");
            UI.alert("오류: 로그인 세션을 가져오지 못했습니다. 페이지를 새로고침 후 다시 로그인하고 시도해주세요.");
            return;
        }

        let maxPage = 1;
        
        // 1. 가져온 HTML 텍스트를 DOM 객체로 변환
        const firstDoc = new DOMParser().parseFromString(firstPageText, 'text/html');
        
        // 2. 코나미 사이트에서 자주 쓰이는 <select> 드롭다운 방식에서 페이지 수 탐색
        const pageOptions = firstDoc.querySelectorAll('select[name="page"] option, select#page option');
        if (pageOptions.length > 0) {
            maxPage = pageOptions.length;
        } else {
            // 3. <a> 태그의 href 속성에서 page 값 탐색
            const pageLinks = firstDoc.querySelectorAll('a[href*="page="]');
            pageLinks.forEach(a => {
                const match = a.href.match(/page=(\d+)/);
                if (match) {
                    const p = parseInt(match[1], 10);
                    if (p > maxPage) maxPage = p;
                }
            });
        
            // 4. 그래도 찾지 못했다면 기존 정규식 방식을 보완하여 적용
            const pageMatches = [...firstPageText.matchAll(/page=(\d+)/g)];
            if (pageMatches.length > 0) {
                const pages = pageMatches.map(m => parseInt(m[1], 10));
                maxPage = Math.max(maxPage, ...pages);
            }
        }
        
        // (선택) 디버깅을 위해 콘솔에 계산된 maxPage 출력
        console.log(`[SDVX Debug] 파싱된 전체 페이지 수: ${maxPage}`);

        let allRecords = [];

        // 2. 데이터 파싱 함수
        const parseRecords = (htmlText) => {
            const doc = new DOMParser().parseFromString(htmlText, 'text/html');
            const rows = doc.querySelectorAll('tr.data_col');
            const pageData = [];

            // ============================================================
            // [핵심 수정 3] HTML 구조 변경에 따른 난이도 클래스명 약자 매핑
            // ============================================================
            const diffMap = { 'nov': 'NOV', 'adv': 'ADV', 'exh': 'EXH', 'mxm': 'MXM', 'inf': 'INF', 'ult': 'ULT' };

            rows.forEach(row => {
                try {
                    const titleElem = row.querySelector('.music .title a');
                    if (!titleElem) return;
                    const title = titleElem.textContent.trim();
                    
                    const artistElem = row.querySelector('.music .artist');
                    const artist = artistElem ? artistElem.textContent.trim() : "";

                    for (const [cls, label] of Object.entries(diffMap)) {
                        const td = row.querySelector(`td.${cls}`);
                        if (!td) continue;

                        const scoreText = td.textContent.trim();
                        // 점수가 없거나 0점인 경우 건너뜀
                        if (scoreText === '0' || !scoreText) continue;

                        let lamp = "PLAYED";
                        const markImg = td.querySelector('img[src*="mark"]');
                        if (markImg) {
                            const src = markImg.src;
                            if (src.includes('mark_no')) continue;
                            else if (src.includes('per')) lamp = "PUC";
                            else if (src.includes('uc')) lamp = "UC";
                            else if (src.includes('comp_ex')) lamp = "EXC CLEAR";
                            else if (src.includes('comp')) lamp = "CLEAR";
                            else if (src.includes('play')) lamp = "FAILED";
                        }

                        let grade = "-";
                        const gradeImg = td.querySelector('img[src*="grade"]');
                        if (gradeImg) {
                            const src = gradeImg.src;
                            if (src.includes('grade_s')) grade = "S";
                            else if (src.includes('aaa_plus')) grade = "AAA+";
                            else if (src.includes('aaa')) grade = "AAA";
                            else if (src.includes('aa_plus')) grade = "AA+";
                            else if (src.includes('aa')) grade = "AA";
                            else if (src.includes('a_plus')) grade = "A+";
                            else if (src.includes('a')) grade = "A";
                            else if (src.includes('b')) grade = "B";
                            else if (src.includes('c')) grade = "C";
                            else if (src.includes('d')) grade = "D";
                        }

                        pageData.push({ Title: title, Artist: artist, Difficulty: label, Score: scoreText, Grade: grade, Lamp: lamp });
                    }
                } catch (e) { console.error("Row parsing error:", e); }
            });
            return pageData;
        };

        // 3. 페이지 순회
        for (let i = 1; i <= maxPage; i++) {
            UI.log(`[${i}/${maxPage}] 데이터 수집 중...`);
            document.title = `[${i}/${maxPage}] 수집 중...`;

            let html = "";
            
            if (i === 1) {
                html = firstPageText;
            } else {
                const pageUrl = `${baseUrl}?limit=${limit}&sort=0&page=${i}&_t=${Date.now()}`;
                const res = await fetch(pageUrl, fetchOptions);
                
                if (!res.ok) {
                    UI.error(`${i}페이지 로드 실패: ${res.status}`);
                    continue;
                }
                html = await res.text();
            }

            if (html.includes("login_form") || html.includes("Basic Course")) {
                UI.error(`${i}페이지에서 로그인이 풀린 것으로 감지되었습니다.`);
                continue;
            }

            const pData = parseRecords(html);
            if (pData.length === 0) {
                UI.log(`  -> 경고: ${i}페이지 기록 0개 (파싱 실패 또는 데이터 없음)`);
            } else {
                allRecords.push(...pData);
                UI.log(`  -> ${pData.length}개 추출 완료`);
            }

            if (i < maxPage) {
                await randomSleep(600, 1100);
            }
        }

        if (allRecords.length === 0) {
            UI.alert("데이터를 하나도 수집하지 못했습니다. F12 콘솔 로그를 확인해주세요.");
            return;
        }

        // 4. CSV 생성 및 업로드
        let csvContent = "Title,Artist,Difficulty,Score,Grade,Lamp\n";
        allRecords.forEach(r => {
            const escape = (txt) => `"${String(txt).replace(/"/g, '""')}"`;
            csvContent += `${escape(r.Title)},${escape(r.Artist)},${escape(r.Difficulty)},${escape(r.Score)},${escape(r.Grade)},${escape(r.Lamp)}\n`;
        });

        UI.log(`총 ${allRecords.length}개의 데이터를 GitHub에 업로드합니다.`);
        
        const apiUrl = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${CONFIG.path}`;
        
        let sha = "";
        try {
            const getRes = await fetch(apiUrl, {
                headers: { 'Authorization': `token ${token}` }
            });
            if (getRes.ok) {
                const getData = await getRes.json();
                sha = getData.sha;
            }
        } catch(e) {}

        const utf8Encoder = new TextEncoder();
        const csvBytes = utf8Encoder.encode(csvContent);
        let binaryString = "";
        csvBytes.forEach(byte => binaryString += String.fromCharCode(byte));
        const contentBase64 = btoa(binaryString);

        const putRes = await fetch(apiUrl, {
            method: 'PUT',
            headers: {
                'Authorization': `token ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: `Update play data via Bookmarklet (${new Date().toLocaleDateString()}) - ${allRecords.length} songs`,
                content: contentBase64,
                sha: sha ? sha : undefined
            })
        });

        if (putRes.ok) {
            UI.alert(`✅ 완료! 총 ${allRecords.length}곡 업데이트 성공.`);
            document.title = "완료!";
        } else {
            const errTxt = await putRes.text();
            UI.alert(`❌ 업로드 실패: ${putRes.status}\n${errTxt}`);
        }

    } catch (err) {
        UI.alert(`🔥 치명적 오류: ${err}`);
        console.error(err);
    }
})();

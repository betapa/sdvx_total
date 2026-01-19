const CONFIG = {
    owner: 'betapa',      // 예: gil-dong
    repo: 'sdvx_total',   // 예: sdvx-data
    path: 'userdata_scraper/sdvx_playdata.csv' // 저장할 파일명
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

        // ============================================================
        // [핵심 수정 1] 쿠키 포함을 위한 공통 헤더 설정
        // credentials: 'include'가 있어야 로그인 세션이 유지됩니다.
        // ============================================================
        const fetchOptions = {
            method: 'GET',
            credentials: 'include', // <--- 가장 중요한 부분 (쿠키 전송)
        };

        // 1. 첫 페이지 로드 및 전체 페이지 수 확인
        const firstPageUrl = `${baseUrl}?limit=${limit}&sort=0&page=1&_t=${Date.now()}`;
        const firstPageRes = await fetch(firstPageUrl, fetchOptions);
        const firstPageText = await firstPageRes.text();
        
        // [디버깅] 첫 페이지가 로그인 페이지인지 확인
        if (firstPageText.includes("login_form") || firstPageText.includes("ea_common_login")) {
            UI.error("세션이 만료되었거나 로그인이 풀려있습니다. e-amusement에 다시 로그인해주세요.");
            UI.alert("오류: 로그인 세션을 가져오지 못했습니다. 페이지를 새로고침 후 다시 로그인하고 시도해주세요.");
            return;
        }

        // [핵심 수정 2] 페이지 수 파싱 로직 강화 (Regex 사용)
        // DOM 파싱보다 HTML 텍스트에서 직접 'page=숫자' 패턴을 찾는 것이 더 안전합니다.
        let maxPage = 1;
        // href="...page=12" 같은 패턴을 모두 찾아서 가장 큰 숫자를 선택
        const pageMatches = [...firstPageText.matchAll(/page=(\d+)/g)];
        if (pageMatches.length > 0) {
            const pages = pageMatches.map(m => parseInt(m[1], 10));
            maxPage = Math.max(...pages);
        }

        UI.log(`총 ${maxPage} 페이지를 발견했습니다. (파싱된 페이지: ${maxPage})`);

        let allRecords = [];

        // 2. 데이터 파싱 함수
        const parseRecords = (htmlText) => {
            const doc = new DOMParser().parseFromString(htmlText, 'text/html');
            const rows = doc.querySelectorAll('tr.data_col');
            const pageData = [];

            const diffMap = { 'novice': 'NOV', 'advanced': 'ADV', 'exhaust': 'EXH', 'maximum': 'MXM', 'infinite': 'INF', 'ultimate': 'ULT' };

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
                        if (scoreText === '0') continue;

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
                // 여기서도 credentials: 'include' 필수
                const res = await fetch(pageUrl, fetchOptions);
                
                if (!res.ok) {
                    UI.error(`${i}페이지 로드 실패: ${res.status}`);
                    continue;
                }
                html = await res.text();
            }

            // [디버깅] 각 페이지가 정상적으로 로그인 상태인지 체크
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
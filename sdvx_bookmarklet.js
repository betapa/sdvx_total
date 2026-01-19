const CONFIG = {
    owner: 'betapa',      
    repo: 'sdvx_total',   
    path: 'sdvx_playdata.csv' 
};

(async function() {
    let token = localStorage.getItem('GH_TOKEN');
    if (!token) {
        token = prompt("GitHub Personal Access Token을 입력해주세요.\n(repo 권한 필요)");
        if (!token) return alert("토큰이 없어 취소합니다.");
        localStorage.setItem('GH_TOKEN', token);
    }

    const UI = {
        log: (msg) => console.log(`%c[SDVX] ${msg}`, 'color: cyan; font-weight: bold;'),
        error: (msg) => console.log(`%c[SDVX Error] ${msg}`, 'color: red; font-weight: bold;'),
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

        const firstPageRes = await fetch(`${baseUrl}?limit=${limit}&sort=0&page=1&_t=${Date.now()}`, {
            credentials: 'include' // 쿠키 포함 강제
        });
        const firstPageText = await firstPageRes.text();
        
        const parser = new DOMParser();
        const doc = parser.parseFromString(firstPageText, 'text/html');

        let maxPage = 1;
        const pageSpans = doc.querySelectorAll('span.page_num');
        if (pageSpans.length > 0) {
            const lastNum = pageSpans[pageSpans.length - 1].textContent;
            maxPage = parseInt(lastNum, 10) || 1;
        } else {
            const pagingBox = doc.querySelector('div.paging_box'); 
            if (pagingBox) {
                const txt = pagingBox.textContent;
                const matches = txt.match(/\/([0-9]+)/);
                if (matches) maxPage = parseInt(matches[1], 10);
            }
        }

        UI.log(`파싱된 총 페이지 수: ${maxPage}`);
        if (maxPage === 1 && pageSpans.length === 0) {
            UI.error("경고: 페이지 번호를 찾지 못했습니다. 로그인이 풀려있거나 HTML 구조가 변경되었을 수 있습니다.");
            console.log("DEBUG HTML:", firstPageText.substring(0, 500)); 
        }

        let allRecords = [];

        // 데이터 파싱 함수
        const parseRecords = (htmlText) => {
            const doc = new DOMParser().parseFromString(htmlText, 'text/html');
            const rows = doc.querySelectorAll('tr.data_col');
            const pageData = [];

            // 로그인 풀림 체크
            if (htmlText.includes("login") || htmlText.includes("e-amusement gate")) {
                UI.error("로그인이 필요한 페이지가 감지되었습니다. (세션 만료 가능성)");
                return [];
            }

            const diffMap = { 
                'novice': 'NOV', 'advanced': 'ADV', 'exhaust': 'EXH', 
                'maximum': 'MXM', 'infinite': 'INF', 'ultimate': 'ULT' 
            };

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
            UI.log(`[${i}/${maxPage}] 데이터 요청 중...`);
            document.title = `[${i}/${maxPage}] 수집 중...`; 

            let html = "";
            
            if (i === 1) {
                html = firstPageText;
            } else {
                try {
                    const res = await fetch(`${baseUrl}?limit=${limit}&sort=0&page=${i}&_t=${Date.now()}`, {
                        credentials: 'include'
                    });
                    
                    if (!res.ok) {
                        UI.error(`  -> ${i}페이지 HTTP 오류: ${res.status}`);
                        continue;
                    }
                    html = await res.text();
                } catch (fetchErr) {
                    UI.error(`  -> ${i}페이지 네트워크 오류: ${fetchErr}`);
                    continue;
                }
            }

            const pData = parseRecords(html);
            
            // 디버깅: 각 페이지별 추출 개수 로그
            if (pData.length === 0) {
                UI.error(`  -> ${i}페이지에서 데이터를 찾지 못했습니다. (HTML 구조 확인 필요)`);
                // 빈 데이터가 나오면 HTML 일부를 찍어서 확인
                // console.log(html.substring(0, 500)); 
            } else {
                UI.log(`  -> ${i}페이지: ${pData.length}개 기록 추출 완료`);
                allRecords.push(...pData);
            }

            if (i < maxPage) {
                await randomSleep(600, 1100);
            }
        }

        UI.log(`총 수집된 기록 수: ${allRecords.length}`);

        if (allRecords.length === 0) {
            return UI.alert("수집된 데이터가 없습니다. 콘솔(F12)을 확인해주세요.");
        }

        // 4. CSV 생성
        let csvContent = "Title,Artist,Difficulty,Score,Grade,Lamp\n";
        allRecords.forEach(r => {
            const escape = (txt) => `"${String(txt).replace(/"/g, '""')}"`;
            csvContent += `${escape(r.Title)},${escape(r.Artist)},${escape(r.Difficulty)},${escape(r.Score)},${escape(r.Grade)},${escape(r.Lamp)}\n`;
        });

        // 5. GitHub 업로드
        UI.log("GitHub에 업로드 준비 중...");
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
                message: `Update play data (${allRecords.length} records) via Bookmarklet`,
                content: contentBase64,
                sha: sha ? sha : undefined
            })
        });

        if (putRes.ok) {
            UI.alert(`완료! 총 ${allRecords.length}곡 업데이트 성공.`);
            document.title = "완료!";
        } else {
            const errTxt = await putRes.text();
            UI.alert(`업로드 실패: ${putRes.status}\n${errTxt}`);
        }

    } catch (err) {
        UI.alert(`치명적 오류 발생: ${err}`);
        console.error(err);
    }
})();
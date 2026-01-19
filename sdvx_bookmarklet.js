const CONFIG = {
    owner: 'betapa',
    repo: 'sdvx_total',
    path: 'sdvx_playdata.csv'
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
        alert: (msg) => alert(`[SDVX Helper]\n${msg}`)
    };

    // Python의 get_random_sleep(600, 1100) 구현
    const randomSleep = (min, max) => {
        const ms = Math.floor(Math.random() * (max - min + 1) + min);
        return new Promise(resolve => setTimeout(resolve, ms));
    };

    try {
        UI.log("데이터 수집을 시작합니다...");

        const limit = 150; 
        const baseUrl = "https://p.eagate.573.jp/game/sdvx/vii/playdata/musicdata/index.html";

        // 1. 첫 페이지 로드 및 전체 페이지 수 확인
        // 캐시 방지를 위해 timestamp 추가
        const firstPageRes = await fetch(`${baseUrl}?limit=${limit}&sort=0&page=1&_t=${Date.now()}`);
        const firstPageText = await firstPageRes.text();
        
        const parser = new DOMParser();
        const doc = parser.parseFromString(firstPageText, 'text/html');

        // Python 로직: matches[-1] (마지막 페이지 번호 추출)
        const pageSpans = doc.querySelectorAll('span.page_num');
        let maxPage = 1;
        if (pageSpans.length > 0) {
            const lastSpan = pageSpans[pageSpans.length - 1];
            maxPage = parseInt(lastSpan.textContent, 10) || 1;
        }

        UI.log(`총 ${maxPage} 페이지를 발견했습니다.`);

        let allRecords = [];

        // 2. 데이터 파싱 함수 (Python 로직 이식)
        const parseRecords = (htmlText) => {
            const doc = new DOMParser().parseFromString(htmlText, 'text/html');
            const rows = doc.querySelectorAll('tr.data_col');
            const pageData = [];

            // Python의 diff_map
            const diffMap = { 
                'novice': 'NOV', 
                'advanced': 'ADV', 
                'exhaust': 'EXH', 
                'maximum': 'MXM', 
                'infinite': 'INF', 
                'ultimate': 'ULT' 
            };

            rows.forEach(row => {
                try {
                    // 곡 제목
                    const titleElem = row.querySelector('.music .title a');
                    if (!titleElem) return;
                    const title = titleElem.textContent.trim();
                    
                    // 아티스트
                    const artistElem = row.querySelector('.music .artist');
                    const artist = artistElem ? artistElem.textContent.trim() : "";

                    for (const [cls, label] of Object.entries(diffMap)) {
                        const td = row.querySelector(`td.${cls}`);
                        if (!td) continue;

                        const scoreText = td.textContent.trim();
                        // 점수가 0이면 스킵
                        if (scoreText === '0') continue;

                        // 램프 분석
                        let lamp = "PLAYED";
                        const markImg = td.querySelector('img[src*="mark"]');
                        if (markImg) {
                            const src = markImg.src;
                            if (src.includes('mark_no')) continue; // 플레이 안 함
                            else if (src.includes('per')) lamp = "PUC";
                            else if (src.includes('uc')) lamp = "UC";
                            else if (src.includes('comp_ex')) lamp = "EXC CLEAR";
                            else if (src.includes('comp')) lamp = "CLEAR";
                            else if (src.includes('play')) lamp = "FAILED";
                        }

                        // 등급 분석
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

                        pageData.push({ 
                            Title: title, 
                            Artist: artist, 
                            Difficulty: label, 
                            Score: scoreText, 
                            Grade: grade, 
                            Lamp: lamp 
                        });
                    }
                } catch (e) { console.error("Row parsing error:", e); }
            });
            return pageData;
        };

        // 3. 페이지 순회 (1페이지부터 maxPage까지)
        for (let i = 1; i <= maxPage; i++) {
            UI.log(`[${i}/${maxPage}] 데이터 수집 중...`);
            document.title = `[${i}/${maxPage}] 수집 중...`; // 탭 제목 업데이트

            let html = "";
            // 1페이지는 이미 받아왔으므로 재사용 (Python 코드: if k == 1 logic)
            if (i === 1) {
                html = firstPageText;
            } else {
                // 페이지 로드 (캐시 방지용 timestamp 추가)
                const res = await fetch(`${baseUrl}?limit=${limit}&sort=0&page=${i}&_t=${Date.now()}`);
                if (!res.ok) {
                    UI.log(`  -> ${i}페이지 로드 실패: ${res.status}`);
                    continue;
                }
                html = await res.text();
            }

            const pData = parseRecords(html);
            if (pData.length === 0) {
                UI.log(`  -> 경고: ${i}페이지 기록 0개`);
            } else {
                allRecords.push(...pData);
                UI.log(`  -> ${pData.length}개 추출 완료`);
            }

            // Python과 동일하게 랜덤 대기 (서버 부하 방지)
            if (i < maxPage) {
                await randomSleep(600, 1100);
            }
        }

        // 4. CSV 생성
        let csvContent = "Title,Artist,Difficulty,Score,Grade,Lamp\n";
        allRecords.forEach(r => {
            const escape = (txt) => `"${String(txt).replace(/"/g, '""')}"`;
            csvContent += `${escape(r.Title)},${escape(r.Artist)},${escape(r.Difficulty)},${escape(r.Score)},${escape(r.Grade)},${escape(r.Lamp)}\n`;
        });

        // 5. GitHub 업로드
        UI.log("GitHub에 업로드 중...");
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

        // UTF-8 인코딩
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
                message: `Update play data via Bookmarklet (${new Date().toLocaleDateString()})`,
                content: contentBase64,
                sha: sha ? sha : undefined
            })
        });

        if (putRes.ok) {
            UI.alert(`완료! 총 ${allRecords.length}곡의 기록이 업데이트되었습니다.`);
            document.title = "완료!";
        } else {
            const errTxt = await putRes.text();
            UI.alert(`업로드 실패: ${putRes.status}\n${errTxt}`);
        }

    } catch (err) {
        UI.alert(`오류 발생: ${err}`);
        console.error(err);
    }
})();
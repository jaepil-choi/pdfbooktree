# 3.6 정규분포

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 123-134

<!-- page 123 -->

정규분포

이항분포의 누적 확률을 적분으로 나타내는 근사식54) 2% Z- mp a V2ㅠ dz, 7->00 2:0s Vap(1-희 56 에서의 함수 p(z)=

## V 2ㅠ

-e ,-8<~≤+8 는 그 적분 값55)이 1이 되는 함수로서 표준정규분포( 3FE 5EA) 75, standard normal distribution)의 확률밀도함수라고 한다. 일반적으로 함수

## 2- A

(2- 10): 2a , -∞<&<+∞ (A는 실수, 0는 양수) 를 정규분포의 확률밀도함수라고 하고, 그림 3.6.1 정규분포 N(4,o2) 의 형태 이 분포를 기호로는 N(W,or)으로 나 0.41 타낸다.

## 정규분포의 확률은 부록 II에 소개

0.3-

## N(-5,3)

## N(5,3)

## 되어 있는 패키지 R을 이용하여 계산할

0.2_ 수 있으며 이를 이용하여 <그림 3.6.12 0.1 과 같이 정규분포의 형태를 그릴 수 있

## N(-5,1)

## N(5,1)

다. 이러한 정규분포의 형태는 2= 4에 0.0 대칭인 종 모양의 곡선으로서, o는 분 어 포의 흩어진 정도를 나타내고 있다. 정리 3.6.1 정규분포의 성질 (a) X~N(, o2)이면 B(X)= A, Var(X) = 02

## 54) 드모아브르(De Moivre)-라플라스(Laplace) 정리로 알려진 이 근사식의 증명은 부록 1.7.에

55) 이 함수의 적분 값은 극좌표 변환을 이용하여 구할 수 있음을 부록 I의 <예 1.6.12에

주어져 있다. 서 밝혔다. 128 3장 여러 가지 확률분포

<!-- page 124 -->

(b) X~N(W,o%)이면 그 적률생성함수는 mgfx (t)= 042+ 들어준 ,-8Ct〈f8

## (c) X~N(1:01), X2~N(W2: 03)이고 X1, X2가 서로 독립이면

## X,tX2~N(+12;0:+02)

[증명] (a) 쯔-쓰 = 2로 치환하여 0(z)=-

- 흑2

에 관한 적분으로 나타 내면 zp(z)dath 여기에서 22/2= 3로 치환하여 적분하면 / zd(z)dz = eNdy+- eUdy=0:. E(X)=A 같은 방법으로 Var (x)=/ 220(z) da 그런데 부록 1의 <예 1.6.2>에서 21(3/2)= 2T(1/2+1)= 2(1/2)T(1/2)= V ::/ 220(z)dz= 1, Var(X)= 02 (6) 프림쓰= 3로 치환하여 0(z)=V2iC 에 관한 적분으로 나타내면 mgfx (t)=/" •+ 00 . 0 •∞ elloatm)o(z)dz 여기에서 다음과 같이 x-at= y로 치환하여 적분하면 / elorp(a)dz=/ -를(2-01)2 23 020라

## V 2ㅠ

:: mgfx(t)=/ ello+mola)de 10“+블0 , -8AtA+8

<!-- page 125 -->

(c) 서로 독립인 확률변수의 합에 관한 <정리 2.5.11>과 (b)로부터 mgx3.4)=m96.timghxt)=exp(tps)t+를(0+03)2. -8Kt<+8

## 우변은 N(Mr+A2; 1+03) 분포의 적률생성함수이므로, 적률생성함수의 분

포 결정성으로부터

## X:+82~N(Mt12;01+02)

정리 3.6.2 정규분포의 대의적 정의 (a) X~N(w,o%)이면 상수 a, b에 대하여 aX+6~N(au+6,0202)

## (6) X~N(1,92) 6

X-"~N(O1)exeOZ+A2~N(0.1) [증명] (a) aX+ 6의 적률생성함수가 mgfax+o(t)=Ele'ox+b]=mgfx (at)em 로 주어지므로, mglas+(t)=exp(be+/(at)+클o(a))=exp(au+6)+½(002)2. -8AtAt8 우변은 N(a+ 6,0:02)분포의 적률생성함수이므로, 적률생성함수의 분포 결 정성으로부터 aX+6~N(au+6,0:02) 이고, (b)는 (a)의 특별한 경우이다. 이러한 정규분포의 성질로부터 정규분포의 누적확률은 표준정규분포를 이용하여 구 할 수 있음을 알 수 있다. 즉 표준정규분포의 누적분포함수를 라고 하면, 일반적인 정규분포 N (4, o2)를 따르는 X의 누적확률은 PIX 5B)=P(즈.쓰S 프)=O(프스) 130 3장 여러 가지 확률분포

<!-- page 126 -->

와 같이 구할 수 있다. 이러한 누적확률은 부록 II에 소개되어 있는 패키지 R을 이용하여 계산할 수 있으 며, 특히 표준정규분포의 누적확률은 부록 IV에 표로도 주어져 있다. 이 표에서 예를 들면 9(1.64)= 0.9195, 9(1.65)= 0.9505, 9(1.96)= 0.9750 한편, 표준정규분포는 0에 관해 대칭이므로 <그림 3.6.2>에서 알 수 있듯이 5(-2)=1-$(2) 이다. 즉 다음과 같이 음수 이하의 누적확률을 구할 수 있다. E(-1.96)= 1-D(1.96) = 0.0250 그림 3.6.2 표준정규분포의 누적확률 5(2) 5(-2) 1-$(2) 예 3.6.1

## X~ N(3,4)일 때 부록 IV의 표를 이용하여 다음 확률을 구하여라.

## (a) P(5CX S 7)

(b) P(1CX ≤ 4) (c) P(X> 0) [풀이] Z=

## X-3

v4

## 2~ N (0,1)이므로 구하는 확률을 다음과 같이 계산할 수 있다.

(a) P(SCX 57)=073)-053 =9(2.0)-9(1.0) = 0.9772- 0.8413 = 0.1359 (6) P(1CX≤4)=61005 70=9(0.5)-9(-1.0) =$(0.5)-(1-$(1.0)) :. P(1CX S 4)= 0.6915-(1-0.8413) = 0.5328

<!-- page 127 -->

(0) P03 20)=1-PIX 50)=1-여0)=1-0(-05) .. P(X>0)= 1-5(-0.5)= 5(0.5)= 0.6915

## 한편, Z ~N(0,1)일 때

그림 3.6.3 표준정규분포의 P(2222)=a(0<a<1) 상방 분위수 를 만족시키는 값 2.를 표준정규분포의 상방 a 분위수(upper a quantile)라고 한다. 이러한

## 상방 분위수는 패키지 R이나 부록 IV의 표를

a 이용하여 구할 수 있다. 예를 들면 20.025 = 1.96, 20.05 = 1.645 따라서 <정리 3.6.2로부터 정규분포 N(4, o2)의 상방 a 분위수는 A+o2.로 주 어진다. 즉 X~N((,o2)일 때 P(X>A+02a)=0 예 3.6.2

## X~N(3,4)일 때 다음 분위수 90.95와 90.025를 구하여라.

(a) P(X S 90.95) = 0.95 (6) P(X S 90.025) = 0.025 [풀이] (a) P (X> 90.95) = 0.05 이므로 90.95 = 3+ 220.05 = 6.290 (6) P(X > 90.025) = 0.975 이므로 90.025 = 3+ 220.975 = 3- 20.025 = - 0.92 정규분포의 성질 : (1N(2,02)=ON(0,1)+A (2) aN(w,02)+6=N(au+6,0:02) (3) N(1,03)@N(2:03)=N(+A2,0%+02) 132 3장 여러 가지 확률분포

<!-- page 128 -->

여러 가지 분포의 정의 분포의 명칭과 기호 확률밀도함수 (distribution) (pdf) (representational definition) 대의적 정의 이항분포 (m0(1-0) x~B(mp) X=2,++21 B(np) 0≤p≤1 2= 0,1, ,n Z,~Bernoulli(p) (i=1,…,7) iid 베르누이분포 Bernoulli(p) p"(1-p)12, 2=0,1 B (1,p) O≤PS1 음이항분포 Negbin (r,p) x~Negbin(70) ex=2,++2, 0<p<1,r:자연수 2=7,7+1, 2,~Geo(p)(&=1,7) 기하분포 Geo(p) 0<pC1 (1-p) -1p, 2=1,2, Negbin (1,p) 포아송분포 Poisson(1) 1≥0 2! -, 2=0,1, 다항분포 X=(X1),Xx), p=(p,Px)' Multi(n(p1P2px)) x~Muti(p) eX을,++2 2,=0, .n(i=1,2,,k) 2itl2t…+&x=n 2, Multi(1,p) (3=1,7) Z,=(Zil;Zk)' 감마분포 a=r이 자연수인 경우: Gamma(a,3) a≥0, 3≥0 ralg zolealo(a) xGamma(rs) ex=레++2, Z,~Exp(3)(i=1,,7) 지수분포 Exp(1/2) 1>0 de-he lo.co)(a) Gamma(1,1/1) 정규분포 N(4,o2) -® X~N(4,q2) A: 실수, 0>0

## 18A3A8

E X=oZ+A, Z~N(0,1)

<!-- page 129 -->

여러 가지 분포의 생성함수 분포의 명칭과 기호 적률생성함수 누율생성함수 (distribution) (mgf) (cgi) 이항분포 (pe'+q)", q=1-P nlogll+p(e'-1)} B(np) 0≤p≤1 -8 Kt<+8 음이항분포 -rlog(1-p-'(1-e-')) Negbin (r:p) tpe'(1-ge)-1), 9=1-p 0<p<1, 7:자연수 t<-logg 포아송분포 Poisson(A) 1≥0 -8AtA18 다항분포 Multi(p,(Pi,Pz)P,)) (pe" ++p,et)" -8<t,<+∞ 0,20. 50=1 (j=1,…,k) 감마분포 Gamma(a,5) (1-3t)-a a≥0, 3≥0 t≤1/3 정규분포

## N(4,9)

k:실수, 0≥0 -8<tC48 134 3장 여러 가지 확률분포

<!-- page 130 -->

다변량 정규분포 신뢰집합 치환 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확률적분변환 점근 대수의 법칙 중심극한정리 표본회귀계수 단순 설명변수 표본적률 극한분포 점근분포 평균오치 난수 첨예도 [붕난수 표본상관계수 분위수 분산안정변환 표본분위수 가능도 추정법 주정 추정량 몬테칼로적분 다중모수 지수족 공간 점수함수 연습문제 가능도방정식 일치성 가능도 함수 적률이용추정량 쿨백-라이블러 괴리도 순오목함수 확률측도 정사영 조건부확률 공리 최소제곱 추정법 확률 최소제곱 추정량 점근정규성 표본공간 표함수 확률밀도함수 랜덤한 실험 확률변수 사전 사후 독립 가산가법성 평규 기댓값 연속형 이산형 표주평차 이상 확률분포 확률질량함수 표주화

## 3.1 이항분포 B(p.p)의 확률밀도함수

f(z)= Ip°(1-p)"-1 , 2= 0, 1,0,n 에 대하여 부등식 f(z)≥ f(2-1)을 풀고, 이로부터 J(a)를 최대로 하는 2값은 2= [(n+1)pl : (n+1)p 이하의 최대 정수 임을 밝혀라. 이와 같이 확률밀도함수를 최대로 하는 값을 최빈값(0)값, mode)이라고 한다.

## 3.2 확률변수 X가 이항분포 B(p,p)를 따를 때

E[X(X-1)(X-r+1)]=n(”-1)… (n-y+1)p'(r= 1,,n) 임을 밝혀라. 이와 같은 기댓값을 1차 계승적률(제휴, factorial moment)이 라고 한다. 3.3 확률변수 X가 이항분포 B(p.p) (0<P<1)를 따를 때 연습문제 (1. 19)에서

## 정의된 X의 왜도와 첨예도를 구하여라.

3.4 X=(X,,…•,Xx)' ~ Multi(n, (p1,,Px)')일 때 다음을 밝혀라. (a) (X1,.X,,n-X,-…-X.) ~Multi(n,(pp)-P1--P.)') (1SrCk) (b) X,= 211,X,= 2,인 조건에서 (X,+1,…,kk) 의 조건부확률밀도함수 를 구하여라. 6_ 확률변수 X가 기하분포 Geo(p) (0 <p< 1)를 따를 때 P(X>R+jX>R)=P(X>j) (j,k=0,1, )

<!-- page 131 -->

임을 밝혀라. 이를 기하분포의 무기억증( 1분유, memoryless property)이라고 한다.

## 3.6 음이항분포 Negbin(r,p) 의 확률밀도함수

J(c)=(31)p (1-p), 2= 7,7+1,·· 에 대하여 부등식 f(2)≥ f(2-1)을 풀고, 이로부터 f(2)를 최대로 하는 2 값은 2= [(r-1)/p]+1 임을 밝혀라. 3.7 확률변수 X가 음이항분포 Negbin (r,p)(0<p<1)를 따를 때 연습문제

## (1.19)에서 정의된 X의 왜도와 첨예도를 구하여라.

3.8 서로 독립이고 성공률이 p(0<p< 1)인 베르누이시행 X1, …, X,,,…을 관측할 때 7번째 성공까지의 시행횟수를 W, 이라고 하면 Cov(Wi, W,) (x≥ 2)를 구하여라.

## 3.9 포아송분포 Poisson (A)의 확률밀도함수

f(2)=e-*X/z!, 2= 0,1,2, 에 대하여 부등식 f(z)≥ f(2- 1)을 풀고, 이로부터 f(x)가 2= [시]에서 최대가 되는 것을 밝혀라. 3.10 확률변수 X가 포아송분포 Poisson(A)(A> 0)를 따를 때 연습문제 (1.19)

## 에서 정의된 X의 왜도와 첨예도를 구하여라.

## 3.11 확률변수 X1, ,X가 서로 독립이고 각각이 포아송분포 Poisson (1:)

(i=1,…,k)를 따를 때, X,+…+Xk=n인 조건에서 (X1, ,Xk)의 조 건부확률밀도함수를 구하여라. 136 3장 여러 가지 확률분포

<!-- page 132 -->

3.12 발생률이 1인 포아송과정 (Ne :t≥ 0}에서 7번째 현상이 발생할 때까지 의 시간을 W,=minft:N, 2rk(7=1,2,…) 이라고 할 때 다음에 답하여라. (a) 사건 (W, >t)을 N,에 관한 식으로 표현하고, 다음 등식이 성립하는 이 유를 설명하여라. (b) Cor(Wi, W,)(≥ 2)을 구하여라. 3.13 확률변수 X가 지수분포 Exp(1/X)(A> 0)를 따를 때 P(X>atyX> 2)=P(X> p)(2≥ 0,9≥0) 임을 밝혀라. 이를 지수분포의 무기억증이라고 한다.

## 3.14 감마분포 Gamma(a,(3)의 확률밀도함수

f(a)= 이 T(a)30 720-le-2/81(0,+0) (2) 에 대하여 a> 1인 경우에 f(z)를 최대로 하는 2 값은 2=(a-1)3임을 밝혀라.

## 3.15 확률변수 X가 감마분포 Gamma(a,3)를 따를 때 연습문제 (1.19)에서 정

## 의된 X의 왜도와 첨예도를 구하여라.

## 3.16 확률변수 X의 적률생성함수가 존재하고

E(X2)=(2k)!/(2), E(X26-1)=0, k= 1,2,

## 일 때 X의 적률생성함수와 확률밀도함수를 구하여라.

3.17 확률변수 X가 정규분포 N(4,o2)(o> 0)를 따를 때 연습문제 (1.19)에서

## 정의된 X의 왜도와 첨예도를 구하여라.

<!-- page 133 -->

## 3.18 양수의 값을 취하는 확률변수 X에 대하여 1ogX~ N(4,o2)일 때 X의 분

포를 로그정규분포(log normal distribution)라고 하며 기호로는 X ~ Lognormal(w,o2) 이라고 나타낸다. 이러한 로그정규분포에 관한 다음 성질 을 밝혀라. (a) X~Lognormal(w,o2)이면 E(Xh)=exp(ku+8282/2), k= 1,2, (6) X~ Lognormal(0,1) 일 때 X의 적률생성함수는 존재하지 않는다. (참고: 2≥ V 12/¢ _exp(te )

## V 2ㅠ

=e:2dz= +∞, Vt≥ 0)

<!-- page 134 -->

robability density function riment) 확률변수(He random variable) 이산형(16 discrete type) 확률질량함수(69 2l probability mass fuction) 확률밀도함수(THE ) function) 평균(Tt mean) 기댓값(WA값 expected value) 표준편차(131분 standard deviation) 표준화(#ft standardized) 누적분포함수 연속형(표 continuous type) 이상(wit improper) 확률분포(8f probability distribution) 지표함수(163 9 주소 Npal probabilty generating function) 18g cumulative distribution function) 표준지수분포(%) standard exponential distribution) 급수(류:# power series) 확률생 www cumulant generating function) 누율(98 cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분 (iterated integra) 적률생성함수(110 ga moment generating function) 적률(1% moment) 누율생성하 적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating function) 합누율(joint/ joint) 주변 (B marginal) 공분산(#AW covariance) 상관계수(ABB) 6% a correlation coefficient) 결합적률 '유슴#품 joint mon nal variance) 회귀함수(미: regression function) 평균제곱예측오차(mean squared prediction error) 행벡터 조건부(1%fww conditional) 조건부평균 (conditional mean) 조건부기댓값(conditional expected value) 조건부분산 ative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(641 popul vector) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 집단분포(9#배AT population distribution) 비복원추출(sampling without replace (Alts population proportion) 초기하분포(※(A f hypergeome 순랜덤추출(Bat랜덤tttl simple randorn sampling) 랜덤표본(random sampl bution) 복원추출(1) tt.lth sampling with replacement) 이항분 t binomial distribution) 대의적 정의(fta8) 1층 repr onal definition 다항분포(81fT) multinomial di 분포(월10)f th geometric distribution n) 다항계수(&TE6%w multinomial coefficie 포 (6 tion) 음이항전개식(negative It t negative binomia expansion) 포아송(Poiss 송 과정(Poisson process) ccurrence rate) 정상성 rity) 독립증분성 (indepe

## 1) 희귀성(rareness) 지수분

crement) 비례성(propo nential distribution) 감마분 표본분포 na distribution) 형상모수(TEAH치 pe parameter) 척도모수(R표다% normal distribution) 분위수(upper quanti ameter) 표준정규분포(1)

## * TERST S

2간(차방꼬미 parameter space) 통계량(MEBt m stal 본비율 nean) 표본분산(174w sample variance) 순서통계량(NET Mat (1A Lt※ sample proportion) 표본평균(푸드) g distribution) 위치모수(11콜 statistics) 표본중앙값(14대 5값 sample medi an) 표본분포(#743) er) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(195916 uniform distribuu) location parameter) 척도모수(RI 8월 scalel 분포(chi-squared distribution) 신뢰수준(16가 후 confidence level) 신뢰구간| 분포(=A4f triangular distribution) 야코비안(Jacobian) 자유도(#)R rees of freedon d분류모형 TAE one way classification model) 신뢰집합(1 confidence set) 치환(24 per 8a confidence ion) 정직행렬(nons ingular matrix) 정칙 다변량 정규분포 probability integral transformation) 다변량 정규분포(3월 1E8At multivariate nor K(주값 characteristic value) 선형회귀모형(3유포미호) linear regression model) 설명변수(explanatory variable) 반응변수.. wAt nonsingular multivariate normal distri 곱합(# 비 iable) 계수(al 및 rank) 제급합 mean squared error sum of squares) 중심극한정리(9)(FAi central limit theorem) 극한분포(ARAti limitire

## 회귀계수(I

egression coefficient) 표본회귀계수(sample regression coefficient) 단순 ( mw simple) d ion) 점근분포(Wift asymptotic distribution) 대수의 법칙(치%의 초 law of large numbers) 표본적률(sample moment) 분위수(5)418) ) 표본분위수(배추유11% on coefficient) 분산안정변환 sample quantile) 슬럿츠키(Slutsky) 점근(ii asymptotic) 첨예도(40 kurtosis) 표본상관계수(A AG SH sample ) 몬테칼로적분(Monte Carlo integration) 적률이용추정량(표지##re method of moments estimator(MME)) 추정(1ftT estimation) 추정량(14 variance syabilizing transformation) 난수(al random number) 균등난수(193 8l. uniform randon ator) 일치성 (-ft consistency) 가능도 함수(미& Bw likelihood function) 우도(XIR) 최대가능도 추정법(RXaN H; maximum likelihood d n) 가능도방정식(OBISE 75it likekihood equation) 순오목함수(strictly concave function) 경계(169f boundary) 다중모수 지수족 (3호} 9) 1탑분1k multil 1즘 information number) 최소제곱 추정법(least squares estimation) 최소제곱 추정량(least squares estimator) 열벡터 공간(column space) 정사영(EE) r exponential family of pdf's) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 점근정규성(Wit iEARtt asymptotic normality) 점수함수(score functio endicular projection) 공리(소 axiom) 표본공간(#2ml sample space) 확률(mim probability) 가산가법성(countable additivity) 확률측도 (HESE MBt proba • 실험(random experiment) 확률변수(1월 후 8% random variable) 이산형 (회 discrete type) 확률질량함수(1%로% probability mass fuction) 률밀도; sure) 조건부확률(18fFWWw conditional probability) 사전 wil prior) 사후(54 posterior) 독립(1호 mutually independent) 종속(HER mutually depende 2119 aws probability density function) 연속형(큰% continuous type) 이상(표: improper) 확률분포(miwArth probability distribution) 지표함수()동 9 listribution function) 표준지수분포(Hief standard exponential distribution) 멱급수(88g power series) 확률생성함수(Mt rter wh probability ge function) 평균(푸k) mean) 기댓값(1) 값 expected value) 표준편차(##4 1B standard deviation) 표준화(14ft standardized) 누적분포함수(부천) hE) unction) 적률생성함수(ARTy moment generating function) 적률(wt moment) 누율생성함수(및후소g cumulant generating function) 누율(부 1t) 이변량(bivariate) 확률벡터(random vector) on coefficient) 결합적률(#w joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur 반복적분(iterated integral) 결합( joint) 주변(Wmarginal) 공분산(*유품 covariance) 상관계수(AE SN 66-: -율(joint cumulant) 조건부(1ft Bt conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variand (BSpng regression function) 평균제곱예측오차(mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산: variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(*B population) 모집단 비율(&ltw population proportion) 초기하분포(1)(olat hypergeometric distribution) 복원추출(15ittl sampling with replacement) 이항분포 at population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(월※t랜덤Mw simple random sampling) 랜덤표본(random cient) 기하분포(※/ th geometric distribution) 음이항분포(12-I44) f negative binomial distribution) 음이항전개식(negative binomial expans inomial distribution) 대의적 정의(1.8.09 교록 representational definition 다항분포(31897 multinomial distribution) 다항계수(33196%.. multinor 속(Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성 (proportiona 준정규분포(**# 1ERe t standard normal areness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(HSHAt) 8 shape parameter) 척도모수(RIEt scale pal #AItt sample proportion) 표본평균 배 distribution) 분위수(upper quantile) 모수공간(타호 parameter space) 통계량(8금1로 statistir ((#A+ 맛값 sample medi an) 표본분포( 추ft sampling distribution) 위치모수(1)gh location parameter) 척도모수(RIS 3- sample mean) 표본산 (A sample variance) 순서통계량 (18 order statistis ter) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(K)¥h) hi uniform distribution) 삼각분포(=/4hti triangular distributic H confidence interval) 일원분류모형 acobian) 자유도(athit degrees of freedom) 카이제곱분포(chi-squared distribution) 신뢰수준(1름ve confidence level) 신뢰 (ion) 확률적분변환(FER) 차 맛 probabl integral transformation) 다변량 정규분포(3%로 FRAm multivariate norr 호텔 one Way classification model) 신뢰집합(1름# confidence set) 치환 on) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(ER 3통 FRAm nonsingular multivariate normal distrit 맛(BA값 characteristic value) 선형회귀모형(※|미큐로 linear regression model) 설명변수(explanatory variable) ponse Variable) 계수(|t: rank) 회귀계수(미(Fe regression coefficient) 표본회귀계수(sample regression cr 순(wwt simple) 평균오차제곱합(주]※제곱합 mean squared error sum of squares) 중심극한정리(#•) 5 법칙(가의 l law of large numbers) 표본적률(sample moment) 분위수(A11 quantile) 표본분이 tral limit theorem) 극한분포(MAt limiting distribution) 점근분포(Httyin asymptotic distribution 7ts sample quantile) 슬럿츠키(Slutsky) 점근(iT asymptotic) 첨예도(439k kurtosis) 표본상 브사아저버하
